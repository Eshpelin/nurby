import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../models/models.dart';

/// Admin-only surfaces (issue #173): per-user camera access, the fleet
/// pipeline view, and household-wide Ask runs. Laptop tasks by nature,
/// kept small on the phone.

// ---------------------------------------------------------------------
// Per-user camera access
// ---------------------------------------------------------------------

final _usersProvider = FutureProvider<List<Map<String, dynamic>>>((ref) async =>
    ((await ref.watch(apiClientProvider).getJson('/api/users')) as List)
        .whereType<Map>()
        .map((u) => u.cast<String, dynamic>())
        .toList());

final _userCamerasProvider =
    FutureProvider.family<List<Camera>, String>((ref, userId) async =>
        ((await ref.watch(apiClientProvider).getJson('/api/users/$userId/cameras'))
                as List)
            .whereType<Map>()
            .map((c) => Camera.fromJson(c.cast<String, dynamic>()))
            .toList());

/// The policy, in one place, because it is subtle and the UI has to say
/// it. See shared/camera_access.py.
///
/// A non-admin with zero grants sees every camera: the single-owner
/// no-op. Granting the first camera flips that user into allowlist mode,
/// so what looks like "give them one more camera" is actually "take away
/// every camera but this one". The screen states that before the first
/// grant rather than after.
String accessSummary(int grants, int totalCameras) {
  if (grants == 0) return 'Sees every camera ($totalCameras). No allowlist.';
  return 'Allowlist: $grants of $totalCameras cameras.';
}

class CameraAccessScreen extends ConsumerWidget {
  const CameraAccessScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final users = ref.watch(_usersProvider);
    final cameras = ref.watch(camerasProvider).value ?? const <Camera>[];

    return Scaffold(
      appBar: AppBar(title: const Text('Who sees which cameras')),
      body: users.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text(apiErrorMessage(e))),
        data: (rows) => ListView(
          padding: const EdgeInsets.all(12),
          children: [
            for (final u in rows.where((u) => u['role'] != 'admin'))
              _UserAccessTile(user: u, allCameras: cameras),
            if (rows.every((u) => u['role'] == 'admin'))
              const Padding(
                padding: EdgeInsets.all(24),
                child: Text(
                  'Only admins here, and admins always see everything.',
                  textAlign: TextAlign.center,
                  style: TextStyle(color: NurbyColors.mutedForeground),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _UserAccessTile extends ConsumerWidget {
  const _UserAccessTile({required this.user, required this.allCameras});

  final Map<String, dynamic> user;
  final List<Camera> allCameras;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final id = user['id'] as String;
    final granted = ref.watch(_userCamerasProvider(id)).value;
    final grantedIds = {for (final c in granted ?? const <Camera>[]) c.id};

    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: ExpansionTile(
        title: Text('${user['display_name'] ?? user['email']}',
            style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 14)),
        subtitle: Text(
          granted == null
              ? 'Loading'
              : accessSummary(granted.length, allCameras.length),
          style: const TextStyle(
              color: NurbyColors.mutedForeground, fontSize: 12),
        ),
        childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
        children: [
          if (granted != null && granted.isEmpty)
            const Padding(
              padding: EdgeInsets.only(bottom: 8),
              child: Text(
                'Ticking the first camera switches this person to an '
                'allowlist. They will then see only the cameras ticked '
                'here, not every camera as they do now.',
                style: TextStyle(fontSize: 12, color: NurbyColors.warning),
              ),
            ),
          for (final c in allCameras)
            CheckboxListTile(
              dense: true,
              contentPadding: EdgeInsets.zero,
              controlAffinity: ListTileControlAffinity.leading,
              activeColor: NurbyColors.accent,
              title: Text(c.name, style: const TextStyle(fontSize: 13)),
              value: grantedIds.contains(c.id),
              onChanged: granted == null
                  ? null
                  : (on) async {
                      final api = ref.read(apiClientProvider);
                      try {
                        if (on == true) {
                          await api.postJson('/api/users/$id/cameras/${c.id}');
                        } else {
                          await api.delete('/api/users/$id/cameras/${c.id}');
                        }
                        ref.invalidate(_userCamerasProvider(id));
                      } catch (e) {
                        if (context.mounted) {
                          ScaffoldMessenger.of(context).showSnackBar(
                              SnackBar(content: Text(apiErrorMessage(e))));
                        }
                      }
                    },
            ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------
// Pipeline
// ---------------------------------------------------------------------

final _pipelineProvider = FutureProvider<Map<String, dynamic>>((ref) async =>
    (await ref.watch(apiClientProvider).getJson('/api/system/pipeline-summary')
            as Map)
        .cast<String, dynamic>());

class PipelineScreen extends ConsumerWidget {
  const PipelineScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(_pipelineProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('AI backlog')),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(_pipelineProvider),
        child: async.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => ListView(children: [
            const SizedBox(height: 96),
            Center(child: Text(apiErrorMessage(e))),
          ]),
          data: (p) {
            final cams = (p['cameras'] as List? ?? const [])
                .whereType<Map>()
                .map((c) => c.cast<String, dynamic>())
                .toList()
              ..sort((a, b) => ((b['backlog'] as num?) ?? 0)
                  .compareTo((a['backlog'] as num?) ?? 0));
            final eta = (p['fleet_eta_seconds'] as num?)?.toDouble() ?? 0;

            return ListView(
              padding: const EdgeInsets.all(12),
              children: [
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(14),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '${p['total_queued'] ?? 0} frames waiting',
                          style: const TextStyle(
                              fontSize: 18, fontWeight: FontWeight.w700),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          // The question this page exists for: with N
                          // cameras feeding one model, when is everything
                          // caught up?
                          eta <= 0
                              ? 'Caught up.'
                              : 'Caught up in about ${_eta(eta)} at '
                                  '${(p['frames_per_min'] as num?)?.toStringAsFixed(0) ?? '?'} frames a minute.',
                          style: const TextStyle(
                              color: NurbyColors.mutedForeground, fontSize: 13),
                        ),
                        if (((p['total_high_priority'] as num?) ?? 0) > 0)
                          Padding(
                            padding: const EdgeInsets.only(top: 4),
                            child: Text(
                                '${p['total_high_priority']} high priority',
                                style: const TextStyle(
                                    color: NurbyColors.warning, fontSize: 12)),
                          ),
                        if (((p['total_errors'] as num?) ?? 0) > 0)
                          Padding(
                            padding: const EdgeInsets.only(top: 4),
                            child: Text('${p['total_errors']} errors',
                                style: const TextStyle(
                                    color: NurbyColors.danger, fontSize: 12)),
                          ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 8),
                for (final c in cams)
                  ListTile(
                    dense: true,
                    title: Text('${c['camera_name']}',
                        style: const TextStyle(fontSize: 13)),
                    subtitle: Text(
                      [
                        '${c['status']}',
                        if ((c['reason'] as String?)?.isNotEmpty ?? false)
                          '${c['reason']}',
                        '${((c['avg_latency'] as num?) ?? 0).toStringAsFixed(1)}s per frame',
                      ].join(' · '),
                      style: const TextStyle(
                          color: NurbyColors.mutedForeground, fontSize: 11),
                    ),
                    trailing: Text('${c['backlog'] ?? 0}',
                        style: TextStyle(
                            fontFamily: 'Menlo',
                            fontWeight: FontWeight.w600,
                            color: ((c['backlog'] as num?) ?? 0) > 0
                                ? NurbyColors.warning
                                : NurbyColors.mutedForeground)),
                  ),
              ],
            );
          },
        ),
      ),
    );
  }

  static String _eta(double secs) {
    if (secs < 90) return '${secs.round()} seconds';
    if (secs < 5400) return '${(secs / 60).round()} minutes';
    return '${(secs / 3600).toStringAsFixed(1)} hours';
  }
}

// ---------------------------------------------------------------------
// Ask admin: every run in the household
// ---------------------------------------------------------------------

final _adminRunsProvider = FutureProvider<List<Map<String, dynamic>>>((ref) async =>
    ((await ref.watch(apiClientProvider).getJson('/api/agent/admin/runs')) as List)
        .whereType<Map>()
        .map((r) => r.cast<String, dynamic>())
        .toList());

class AskAdminScreen extends ConsumerWidget {
  const AskAdminScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(_adminRunsProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Everyone\'s questions')),
      body: async.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text(apiErrorMessage(e))),
        data: (runs) => runs.isEmpty
            ? const Center(
                child: Text('Nobody has asked anything yet.',
                    style: TextStyle(color: NurbyColors.mutedForeground)))
            : ListView.builder(
                itemCount: runs.length,
                itemBuilder: (_, i) {
                  final r = runs[i];
                  final failed = r['status'] == 'failed';
                  return ListTile(
                    title: Text('${r['question'] ?? ''}',
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontSize: 13)),
                    subtitle: Text(
                      [
                        if (r['started_at'] != null)
                          DateFormat('MMM d, HH:mm').format(
                              DateTime.parse('${r['started_at']}').toLocal()),
                        '${r['status']}',
                        if (r['cost_cents'] != null)
                          '\$${((r['cost_cents'] as num) / 100).toStringAsFixed(3)}',
                      ].join(' · '),
                      style: TextStyle(
                          fontSize: 11,
                          color: failed
                              ? NurbyColors.danger
                              : NurbyColors.mutedForeground),
                    ),
                  );
                },
              ),
      ),
    );
  }
}
