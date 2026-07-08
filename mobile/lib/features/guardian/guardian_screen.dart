import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';

// ---- Data providers ----

final _linksProvider = FutureProvider<List<Map<String, dynamic>>>((ref) async {
  final j =
      await ref.watch(apiClientProvider).getJson('/api/guardian/me') as Map;
  return (j['links'] as List? ?? [])
      .whereType<Map>()
      .map((l) => l.cast<String, dynamic>())
      .toList();
});

/// Live-ish link status; refreshed every 30s like camerasProvider does.
final _linkStatusProvider =
    FutureProvider.family<Map<String, dynamic>, String>((ref, id) async {
  final timer = Timer.periodic(
      const Duration(seconds: 30), (_) => ref.invalidateSelf());
  ref.onDispose(timer.cancel);
  return (await ref
          .watch(apiClientProvider)
          .getJson('/api/guardian/links/$id/status') as Map)
      .cast<String, dynamic>();
});

/// Recap is optional server-side; soft-fail to null.
final _linkRecapProvider =
    FutureProvider.family<String?, String>((ref, id) async {
  try {
    final j = await ref
        .watch(apiClientProvider)
        .getJson('/api/guardian/links/$id/recap');
    if (j is Map) {
      final text = j['recap'] ?? j['text'] ?? j['summary'];
      final s = text?.toString().trim();
      return (s == null || s.isEmpty) ? null : s;
    }
    final s = j?.toString().trim();
    return (s == null || s.isEmpty) ? null : s;
  } catch (_) {
    return null;
  }
});

final _linkTimelineProvider =
    FutureProvider.family<List<Map<String, dynamic>>, String>((ref, id) async {
  final now = DateTime.now().toUtc();
  final j = await ref
      .watch(apiClientProvider)
      .getJson('/api/guardian/links/$id/timeline', query: {
    'from': now.subtract(const Duration(hours: 24)).toIso8601String(),
    'to': now.toIso8601String(),
  });
  final items = j is List ? j : (j as Map)['items'] as List? ?? [];
  return items.whereType<Map>().map((t) => t.cast<String, dynamic>()).toList();
});

// ---- Helpers ----

bool _isForbidden(Object e) =>
    e is DioException && e.response?.statusCode == 403;

DateTime? _itemTime(Map<String, dynamic> item) {
  for (final key in ['at', 'timestamp', 'time', 'started_at', 'occurred_at']) {
    final v = item[key];
    if (v is String) {
      final dt = DateTime.tryParse(v);
      if (dt != null) return dt.toLocal();
    }
  }
  return null;
}

String _itemText(Map<String, dynamic> item) {
  for (final key in ['text', 'description', 'summary', 'label', 'kind']) {
    final v = item[key];
    if (v is String && v.trim().isNotEmpty) return v;
  }
  return 'Activity';
}

Color _statusColor(String status) => switch (status) {
      'home' => NurbyColors.accent,
      'away' => NurbyColors.warning,
      _ => NurbyColors.mutedForeground,
    };

class _StatusPill extends StatelessWidget {
  const _StatusPill({required this.status});
  final String status;

  @override
  Widget build(BuildContext context) {
    final color = _statusColor(status);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.15),
        border: Border.all(color: color.withValues(alpha: 0.4)),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        status.toUpperCase(),
        style: TextStyle(
          fontFamily: 'Menlo',
          fontSize: 10,
          letterSpacing: 1.2,
          fontWeight: FontWeight.w600,
          color: color,
        ),
      ),
    );
  }
}

/// Guardian mode: remote check-in on linked people (elderly relatives etc).
class GuardianScreen extends ConsumerWidget {
  const GuardianScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final links = ref.watch(_linksProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Guardian')),
      body: links.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) {
          if (_isForbidden(e)) {
            return _infoState(
              icon: Icons.shield_outlined,
              title: 'Guardian mode is for guardian accounts',
              subtitle:
                  'Ask an admin for a guardian invite to link with someone.',
            );
          }
          return _infoState(
            icon: Icons.error_outline,
            title: apiErrorMessage(e),
            subtitle: null,
            onRetry: () => ref.invalidate(_linksProvider),
          );
        },
        data: (list) {
          if (list.isEmpty) {
            return _infoState(
              icon: Icons.link_off,
              title: 'No guardian links connected',
              subtitle: 'Once a link is set up, their status will appear here.',
            );
          }
          return RefreshIndicator(
            color: NurbyColors.accent,
            onRefresh: () async {
              ref.invalidate(_linksProvider);
              await ref.read(_linksProvider.future);
            },
            child: ListView(
              padding: const EdgeInsets.all(12),
              children: [
                for (final link in list)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: _LinkCard(link: link),
                  ),
              ],
            ),
          );
        },
      ),
    );
  }

  Widget _infoState({
    required IconData icon,
    required String title,
    String? subtitle,
    VoidCallback? onRetry,
  }) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 40, color: NurbyColors.mutedForeground),
            const SizedBox(height: 12),
            Text(title,
                textAlign: TextAlign.center,
                style: const TextStyle(
                    color: NurbyColors.foreground, fontSize: 15)),
            if (subtitle != null) ...[
              const SizedBox(height: 6),
              Text(subtitle,
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                      color: NurbyColors.mutedForeground, fontSize: 13)),
            ],
            if (onRetry != null) ...[
              const SizedBox(height: 16),
              OutlinedButton(onPressed: onRetry, child: const Text('Retry')),
            ],
          ],
        ),
      ),
    );
  }
}

class _LinkCard extends ConsumerWidget {
  const _LinkCard({required this.link});
  final Map<String, dynamic> link;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final id = link['id'].toString();
    final name = link['name']?.toString() ?? 'Linked person';
    final status = ref.watch(_linkStatusProvider(id));
    final recap = ref.watch(_linkRecapProvider(id)).value;

    return Card(
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () => Navigator.push(
          context,
          MaterialPageRoute<void>(
            builder: (_) => _GuardianLinkDetailScreen(link: link),
          ),
        ),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(name,
                        style: const TextStyle(
                            fontSize: 16, fontWeight: FontWeight.w600)),
                  ),
                  status.when(
                    loading: () => const SizedBox(
                        width: 14,
                        height: 14,
                        child: CircularProgressIndicator(strokeWidth: 2)),
                    error: (_, __) => const _StatusPill(status: 'unknown'),
                    data: (s) => _StatusPill(
                        status: s['status']?.toString() ?? 'unknown'),
                  ),
                ],
              ),
              status.when(
                loading: () => const SizedBox.shrink(),
                error: (e, _) => Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(apiErrorMessage(e),
                      style: const TextStyle(
                          color: NurbyColors.mutedForeground, fontSize: 12)),
                ),
                data: (s) {
                  final location = s['location']?.toString();
                  final lastSeen =
                      DateTime.tryParse(s['last_seen_at']?.toString() ?? '')
                          ?.toLocal();
                  return Padding(
                    padding: const EdgeInsets.only(top: 8),
                    child: Row(
                      children: [
                        if (location != null && location.isNotEmpty) ...[
                          const Icon(Icons.place_outlined,
                              size: 14, color: NurbyColors.mutedForeground),
                          const SizedBox(width: 4),
                          Text(location,
                              style: const TextStyle(
                                  color: NurbyColors.mutedForeground,
                                  fontSize: 13)),
                          const SizedBox(width: 12),
                        ],
                        if (lastSeen != null)
                          Text(
                            'seen ${DateFormat('MMM d, HH:mm').format(lastSeen)}',
                            style: monoStyle,
                          ),
                      ],
                    ),
                  );
                },
              ),
              if (recap != null) ...[
                const SizedBox(height: 10),
                Text(
                  recap,
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                      color: NurbyColors.foreground,
                      fontSize: 13,
                      height: 1.4),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _GuardianLinkDetailScreen extends ConsumerWidget {
  const _GuardianLinkDetailScreen({required this.link});
  final Map<String, dynamic> link;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final id = link['id'].toString();
    final name = link['name']?.toString() ?? 'Linked person';
    final status = ref.watch(_linkStatusProvider(id));
    final timeline = ref.watch(_linkTimelineProvider(id));

    return Scaffold(
      appBar: AppBar(title: Text(name)),
      body: RefreshIndicator(
        color: NurbyColors.accent,
        onRefresh: () async {
          ref.invalidate(_linkStatusProvider(id));
          ref.invalidate(_linkTimelineProvider(id));
          await ref.read(_linkTimelineProvider(id).future);
        },
        child: ListView(
          padding: const EdgeInsets.all(12),
          children: [
            Card(
              child: Padding(
                padding: const EdgeInsets.all(14),
                child: status.when(
                  loading: () => const Center(
                    child: Padding(
                      padding: EdgeInsets.all(8),
                      child: SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2)),
                    ),
                  ),
                  error: (e, _) => Text(apiErrorMessage(e),
                      style: const TextStyle(
                          color: NurbyColors.mutedForeground, fontSize: 13)),
                  data: (s) {
                    final location = s['location']?.toString();
                    final lastSeen = DateTime.tryParse(
                            s['last_seen_at']?.toString() ?? '')
                        ?.toLocal();
                    return Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            _StatusPill(
                                status:
                                    s['status']?.toString() ?? 'unknown'),
                            const Spacer(),
                            if (lastSeen != null)
                              Text(
                                DateFormat('MMM d, HH:mm').format(lastSeen),
                                style: monoStyle,
                              ),
                          ],
                        ),
                        if (location != null && location.isNotEmpty) ...[
                          const SizedBox(height: 10),
                          Row(
                            children: [
                              const Icon(Icons.place_outlined,
                                  size: 15,
                                  color: NurbyColors.mutedForeground),
                              const SizedBox(width: 5),
                              Text(location,
                                  style: const TextStyle(
                                      color: NurbyColors.foreground,
                                      fontSize: 14)),
                            ],
                          ),
                        ],
                      ],
                    );
                  },
                ),
              ),
            ),
            const Padding(
              padding: EdgeInsets.only(top: 18, bottom: 8, left: 4),
              child: Text(
                'LAST 24 HOURS',
                style: TextStyle(
                  fontFamily: 'Menlo',
                  fontSize: 10,
                  letterSpacing: 1.4,
                  color: NurbyColors.accent,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
            timeline.when(
              loading: () => const Padding(
                padding: EdgeInsets.all(24),
                child: Center(child: CircularProgressIndicator()),
              ),
              error: (e, _) => Padding(
                padding: const EdgeInsets.all(12),
                child: Text(apiErrorMessage(e),
                    style: const TextStyle(
                        color: NurbyColors.mutedForeground)),
              ),
              data: (items) {
                if (items.isEmpty) {
                  return const Padding(
                    padding: EdgeInsets.all(12),
                    child: Text('No activity in the last 24 hours',
                        style:
                            TextStyle(color: NurbyColors.mutedForeground)),
                  );
                }
                return Column(
                  children: [
                    for (final item in items)
                      Card(
                        margin: const EdgeInsets.only(bottom: 8),
                        child: ListTile(
                          title: Text(
                            _itemText(item),
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(fontSize: 13),
                          ),
                          subtitle: _itemTime(item) != null
                              ? Text(
                                  DateFormat('MMM d, HH:mm')
                                      .format(_itemTime(item)!),
                                  style: monoStyle)
                              : null,
                        ),
                      ),
                  ],
                );
              },
            ),
          ],
        ),
      ),
    );
  }
}
