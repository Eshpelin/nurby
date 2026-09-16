import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import 'grant_link_sheet.dart';
import 'guardian_cards.dart';

/// The household side of guardian (issue #165).
///
/// Everything here is about people the household has granted access to,
/// rather than access the household has been granted. The distinction
/// matters enough to be a separate screen: /api/guardian/me answers "who
/// can I watch", /api/guardian/links answers "who can watch us".

final grantedLinksProvider = FutureProvider<List<Map<String, dynamic>>>(
    (ref) => ref.watch(guardianRepoProvider).allLinks());

final accessLogProvider = FutureProvider<List<Map<String, dynamic>>>(
    (ref) => ref.watch(guardianRepoProvider).accessLog());

final facilitiesProvider = FutureProvider<List<Map<String, dynamic>>>(
    (ref) => ref.watch(guardianRepoProvider).facilities());

final pickupsProvider =
    FutureProvider.family<List<Map<String, dynamic>>, String>(
        (ref, personId) => ref.watch(guardianRepoProvider).pickups(personId));

class GuardianAdminScreen extends ConsumerWidget {
  const GuardianAdminScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return DefaultTabController(
      length: 3,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Who can watch us'),
          actions: [
            IconButton(
              tooltip: 'Grant access to someone',
              icon: const Icon(Icons.person_add_alt_1_outlined),
              onPressed: () => showModalBottomSheet<void>(
                context: context,
                isScrollControlled: true,
                backgroundColor: NurbyColors.cardElevated,
                builder: (_) => const GrantLinkSheet(),
              ),
            ),
          ],
          bottom: const TabBar(
            tabs: [
              Tab(text: 'People'),
              Tab(text: 'Access log'),
              Tab(text: 'Places'),
            ],
          ),
        ),
        body: const TabBarView(
          children: [_LinksTab(), _AccessLogTab(), _FacilitiesTab()],
        ),
      ),
    );
  }
}

class _LinksTab extends ConsumerWidget {
  const _LinksTab();

  Future<void> _revoke(
      BuildContext context, WidgetRef ref, Map<String, dynamic> link) async {
    final who = link['relationship_label'] as String? ?? 'this guardian';
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: NurbyColors.cardElevated,
        title: const Text('Revoke access?'),
        // Revoking is immediate and total. Saying what it does not do is
        // as important as saying what it does: the guardian keeps nothing
        // going forward, but what they already saw is already seen.
        content: Text(
          'This stops $who seeing anything from now on. It does not undo '
          'what they have already been shown.',
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Cancel')),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Revoke',
                style: TextStyle(color: NurbyColors.danger)),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await ref.read(guardianRepoProvider).revokeLink(link['id'] as String);
      ref.invalidate(grantedLinksProvider);
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(grantedLinksProvider);
    final vocab = ref.watch(guardianVocabularyProvider).value;
    final tierLabels = {
      for (final t in (vocab?['tiers'] as List? ?? const []).whereType<Map>())
        '${t['key']}': '${t['label']}',
    };

    return async.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => _Retry(
        message: apiErrorMessage(e),
        onRetry: () => ref.invalidate(grantedLinksProvider),
      ),
      data: (links) {
        // A revoked link is kept in the list rather than filtered out.
        // "Nobody can watch us" and "we revoked someone last week" are
        // different facts, and the second one is worth being able to see.
        final active = links.where((l) => l['revoked_at'] == null).toList();
        final revoked = links.where((l) => l['revoked_at'] != null).toList();

        if (links.isEmpty) {
          return const _Empty(
            icon: Icons.shield_outlined,
            title: 'Nobody has been granted access',
            detail: 'A guardian link lets someone outside the household see '
                'a limited view of one person.',
          );
        }
        return RefreshIndicator(
          onRefresh: () async => ref.invalidate(grantedLinksProvider),
          child: ListView(
            padding: const EdgeInsets.all(12),
            children: [
              for (final l in active)
                _LinkRow(
                  link: l,
                  tierLabels: tierLabels,
                  onRevoke: () => _revoke(context, ref, l),
                  onPickups: () => showModalBottomSheet<void>(
                    context: context,
                    isScrollControlled: true,
                    backgroundColor: NurbyColors.cardElevated,
                    builder: (_) => PickupsSheet(
                      personId: l['person_id'] as String,
                      name: l['relationship_label'] as String? ?? 'them',
                    ),
                  ),
                ),
              if (revoked.isNotEmpty) ...[
                const Padding(
                  padding: EdgeInsets.fromLTRB(4, 18, 4, 6),
                  child: Text('Revoked',
                      style: TextStyle(
                          fontSize: 12,
                          color: NurbyColors.mutedForeground,
                          fontWeight: FontWeight.w600)),
                ),
                for (final l in revoked)
                  _LinkRow(link: l, tierLabels: tierLabels, onRevoke: null),
              ],
            ],
          ),
        );
      },
    );
  }
}

class _LinkRow extends StatelessWidget {
  const _LinkRow({
    required this.link,
    required this.onRevoke,
    this.onPickups,
    this.tierLabels,
  });

  final Map<String, dynamic> link;
  final VoidCallback? onRevoke;
  final VoidCallback? onPickups;

  /// Key to label, from /api/guardian/vocabulary.
  final Map<String, String>? tierLabels;

  @override
  Widget build(BuildContext context) {
    final revoked = link['revoked_at'] != null;
    final tier = link['tier'] as String? ?? 'unknown';
    final expires = link['expires_at'] as String?;

    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: ListTile(
        title: Text(
          link['relationship_label'] as String? ?? 'Guardian',
          style: TextStyle(
            fontWeight: FontWeight.w600,
            fontSize: 14,
            color: revoked ? NurbyColors.mutedForeground : null,
          ),
        ),
        subtitle: Text(
          [
            tierLabels?[tier] ?? _tierLabel(tier),
            if (link['live_video'] == true) 'live video',
            if (link['audio'] == true) 'audio',
            if (expires != null) 'until ${_date(expires)}',
            if (revoked) 'revoked ${_date(link['revoked_at'] as String)}',
          ].join(' · '),
          style: const TextStyle(
              color: NurbyColors.mutedForeground, fontSize: 12),
        ),
        trailing: onRevoke == null
            ? null
            : Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  IconButton(
                    icon: const Icon(Icons.how_to_reg_outlined,
                        size: 18, color: NurbyColors.mutedForeground),
                    tooltip: 'Approved pickups',
                    onPressed: onPickups,
                  ),
                  IconButton(
                    icon: const Icon(Icons.link_off,
                        size: 18, color: NurbyColors.mutedForeground),
                    tooltip: 'Revoke',
                    onPressed: onRevoke,
                  ),
                ],
              ),
      ),
    );
  }
}

/// The check on the whole feature: who looked at what, and when.
class _AccessLogTab extends ConsumerWidget {
  const _AccessLogTab();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(accessLogProvider);

    return async.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => _Retry(
        message: apiErrorMessage(e),
        onRetry: () => ref.invalidate(accessLogProvider),
      ),
      data: (rows) => rows.isEmpty
          ? const _Empty(
              icon: Icons.history,
              title: 'Nothing has been looked at yet',
              detail: 'Every time a guardian opens something, it is '
                  'recorded here.',
            )
          : RefreshIndicator(
              onRefresh: () async => ref.invalidate(accessLogProvider),
              child: ListView.builder(
                padding: const EdgeInsets.all(12),
                itemCount: rows.length,
                itemBuilder: (_, i) {
                  final r = rows[i];
                  return ListTile(
                    dense: true,
                    title: Text('${r['action']}',
                        style: const TextStyle(fontSize: 13)),
                    subtitle: Text(
                      [
                        if (r['at'] != null) _dateTime('${r['at']}'),
                        if (r['ip'] != null) '${r['ip']}',
                      ].join(' · '),
                      style: const TextStyle(
                          color: NurbyColors.mutedForeground, fontSize: 11),
                    ),
                  );
                },
              ),
            ),
    );
  }
}

class _FacilitiesTab extends ConsumerWidget {
  const _FacilitiesTab();

  void _editFacility(BuildContext context, Map<String, dynamic>? existing) {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: NurbyColors.cardElevated,
      builder: (_) => _FacilityForm(existing: existing),
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(facilitiesProvider);

    return async.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => _Retry(
        message: apiErrorMessage(e),
        onRetry: () => ref.invalidate(facilitiesProvider),
      ),
      data: (rows) => rows.isEmpty
          ? ListView(children: [
              const _Empty(
                icon: Icons.apartment_outlined,
                title: 'No places configured',
                detail: 'A place groups guardian links, for a school or a '
                    'care home rather than a single household.',
              ),
              Center(
                child: OutlinedButton(
                  onPressed: () => _editFacility(context, null),
                  child: const Text('Add a place'),
                ),
              ),
            ])
          : ListView(
              padding: const EdgeInsets.all(12),
              children: [
                for (final f in rows)
                  Card(
                    margin: const EdgeInsets.only(bottom: 8),
                    child: ListTile(
                      title: Text('${f['name']}',
                          style: const TextStyle(
                              fontWeight: FontWeight.w600, fontSize: 14)),
                      subtitle: Text(
                        [
                          if (f['timezone'] != null) '${f['timezone']}',
                          'up to ${f['max_cameras_per_person'] ?? '?'} cameras each',
                          if (f['is_default'] == true) 'default',
                        ].join(' · '),
                        style: const TextStyle(
                            color: NurbyColors.mutedForeground, fontSize: 12),
                      ),
                      trailing: const Icon(Icons.edit_outlined,
                          size: 18, color: NurbyColors.mutedForeground),
                      onTap: () => _editFacility(context, f),
                    ),
                  ),
                OutlinedButton.icon(
                  onPressed: () => _editFacility(context, null),
                  icon: const Icon(Icons.add, size: 16),
                  label: const Text('Add a place'),
                ),
              ],
            ),
    );
  }
}

/// Approved pickups and consent for one dependant.
class PickupsSheet extends ConsumerStatefulWidget {
  const PickupsSheet({super.key, required this.personId, required this.name});

  final String personId;
  final String name;

  @override
  ConsumerState<PickupsSheet> createState() => _PickupsSheetState();
}

class _PickupsSheetState extends ConsumerState<PickupsSheet> {
  final _name = TextEditingController();
  final _plate = TextEditingController();
  String _kind = 'person';
  bool _busy = false;

  @override
  void dispose() {
    _name.dispose();
    _plate.dispose();
    super.dispose();
  }

  Future<void> _add() async {
    final name = _name.text.trim();
    if (name.isEmpty) return;
    setState(() => _busy = true);
    try {
      await ref.read(guardianRepoProvider).addPickup(
            widget.personId,
            name: name,
            kind: _kind,
            vehiclePlate: _kind == 'vehicle' ? _plate.text.trim() : null,
          );
      _name.clear();
      _plate.clear();
      ref.invalidate(pickupsProvider(widget.personId));
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _remove(String id) async {
    try {
      await ref.read(guardianRepoProvider).removePickup(id);
      ref.invalidate(pickupsProvider(widget.personId));
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(pickupsProvider(widget.personId));

    return Padding(
      padding: EdgeInsets.only(
        left: 16,
        right: 16,
        top: 16,
        bottom: MediaQuery.of(context).viewInsets.bottom + 24,
      ),
      child: SingleChildScrollView(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('Who may collect ${widget.name}',
                style: const TextStyle(
                    fontSize: 16, fontWeight: FontWeight.w600)),
            const SizedBox(height: 4),
            const Text(
              'Nearby people or vehicles can match an approved entry. '
              'A camera match does not confirm a handover; check with staff.',
              style: TextStyle(
                  color: NurbyColors.mutedForeground, fontSize: 12),
            ),
            const SizedBox(height: 12),
            async.when(
              loading: () => const LinearProgressIndicator(),
              error: (e, _) => Text(apiErrorMessage(e),
                  style: const TextStyle(
                      color: NurbyColors.mutedForeground, fontSize: 12)),
              data: (rows) => rows.isEmpty
                  ? const Text('Nobody yet.',
                      style: TextStyle(
                          color: NurbyColors.mutedForeground, fontSize: 12))
                  : Column(
                      children: [
                        for (final p in rows)
                          ListTile(
                            dense: true,
                            contentPadding: EdgeInsets.zero,
                            leading: Icon(
                                p['kind'] == 'vehicle'
                                    ? Icons.directions_car_outlined
                                    : Icons.person_outline,
                                size: 18,
                                color: NurbyColors.mutedForeground),
                            title: Text('${p['name']}',
                                style: const TextStyle(fontSize: 13)),
                            subtitle: p['vehicle_plate'] == null
                                ? null
                                : Text('${p['vehicle_plate']}',
                                    style: const TextStyle(
                                        color: NurbyColors.mutedForeground,
                                        fontSize: 11)),
                            trailing: IconButton(
                              icon: const Icon(Icons.close, size: 18),
                              onPressed: () => _remove(p['id'] as String),
                            ),
                          ),
                      ],
                    ),
            ),
            const Divider(height: 24),
            SegmentedButton<String>(
              segments: const [
                ButtonSegment(value: 'person', label: Text('Person')),
                ButtonSegment(value: 'vehicle', label: Text('Vehicle')),
              ],
              selected: {_kind},
              onSelectionChanged: (v) => setState(() => _kind = v.first),
            ),
            const SizedBox(height: 8),
            TextField(
              controller: _name,
              decoration: const InputDecoration(
                  labelText: 'Name', isDense: true, border: OutlineInputBorder()),
            ),
            if (_kind == 'vehicle') ...[
              const SizedBox(height: 8),
              TextField(
                controller: _plate,
                autocorrect: false,
                textCapitalization: TextCapitalization.characters,
                decoration: const InputDecoration(
                    labelText: 'Number plate',
                    isDense: true,
                    border: OutlineInputBorder()),
              ),
            ],
            const SizedBox(height: 12),
            FilledButton(
              onPressed: _busy ? null : _add,
              child: const Text('Add'),
            ),
          ],
        ),
      ),
    );
  }
}

// ---- shared bits ----

/// Fallback only. The label proper comes from
/// /api/guardian/vocabulary; this reads a raw key rather than showing
/// one when the vocabulary has not landed yet.
String _tierLabel(String tier) => switch (tier) {
      'full' => 'Full access',
      'summary' => 'Recaps',
      'alerts_only' => 'Alerts only',
      _ => tier,
    };

String _date(String iso) {
  final d = DateTime.tryParse(iso);
  return d == null ? iso : DateFormat('MMM d, y').format(d.toLocal());
}

String _dateTime(String iso) {
  final d = DateTime.tryParse(iso);
  return d == null ? iso : DateFormat('MMM d, HH:mm').format(d.toLocal());
}

class _Empty extends StatelessWidget {
  const _Empty({required this.icon, required this.title, required this.detail});

  final IconData icon;
  final String title;
  final String detail;

  @override
  Widget build(BuildContext context) => ListView(
        children: [
          const SizedBox(height: 96),
          Icon(icon, size: 40, color: NurbyColors.mutedForeground),
          const SizedBox(height: 12),
          Center(
            child: Text(title,
                style: const TextStyle(fontWeight: FontWeight.w600)),
          ),
          const SizedBox(height: 6),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 40),
            child: Text(detail,
                textAlign: TextAlign.center,
                style: const TextStyle(
                    fontSize: 12, color: NurbyColors.mutedForeground)),
          ),
        ],
      );
}

class _Retry extends StatelessWidget {
  const _Retry({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) => ListView(
        children: [
          const SizedBox(height: 96),
          Center(
            child: Text(message,
                textAlign: TextAlign.center,
                style: const TextStyle(color: NurbyColors.mutedForeground)),
          ),
          const SizedBox(height: 12),
          Center(
            child:
                OutlinedButton(onPressed: onRetry, child: const Text('Retry')),
          ),
        ],
      );
}


/// Create or edit a facility. Slug is set on create only; the API does
/// not accept it on PATCH, since links already reference it.
class _FacilityForm extends ConsumerStatefulWidget {
  const _FacilityForm({required this.existing});
  final Map<String, dynamic>? existing;

  @override
  ConsumerState<_FacilityForm> createState() => _FacilityFormState();
}

class _FacilityFormState extends ConsumerState<_FacilityForm> {
  late final _name = TextEditingController(text: widget.existing?['name'] as String? ?? '');
  late final _slug = TextEditingController(text: widget.existing?['slug'] as String? ?? '');
  late final _tz = TextEditingController(text: widget.existing?['timezone'] as String? ?? '');
  late double _reveal = ((widget.existing?['reveal_min_confidence'] as num?)?.toDouble() ?? 0.8).clamp(0.5, 1.0);
  late int _maxCams = (widget.existing?['max_cameras_per_person'] as num?)?.toInt() ?? 4;
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _name.dispose();
    _slug.dispose();
    _tz.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (_name.text.trim().isEmpty) {
      setState(() => _error = 'Give it a name.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    final repo = ref.read(guardianRepoProvider);
    final body = {
      'name': _name.text.trim(),
      if (_tz.text.trim().isNotEmpty) 'timezone': _tz.text.trim(),
      'reveal_min_confidence': double.parse(_reveal.toStringAsFixed(2)),
      'max_cameras_per_person': _maxCams,
    };
    try {
      if (widget.existing == null) {
        await repo.createFacility({
          ...body,
          if (_slug.text.trim().isNotEmpty) 'slug': _slug.text.trim(),
        });
      } else {
        await repo.updateFacility(widget.existing!['id'] as String, body);
      }
      ref.invalidate(facilitiesProvider);
      if (mounted) Navigator.pop(context);
    } catch (e) {
      if (mounted) setState(() => _error = apiErrorMessage(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Padding(
        padding: EdgeInsets.only(
          left: 20, right: 20, top: 20,
          bottom: MediaQuery.of(context).viewInsets.bottom + 24,
        ),
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(widget.existing == null ? 'New place' : 'Edit place',
                  style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
              const SizedBox(height: 16),
              TextField(
                controller: _name,
                decoration: const InputDecoration(labelText: 'Name', border: OutlineInputBorder()),
              ),
              if (widget.existing == null) ...[
                const SizedBox(height: 12),
                TextField(
                  controller: _slug,
                  autocorrect: false,
                  decoration: const InputDecoration(
                    labelText: 'Short id (optional)',
                    helperText: 'Used in links. Cannot be changed later.',
                    border: OutlineInputBorder(),
                  ),
                ),
              ],
              const SizedBox(height: 12),
              TextField(
                controller: _tz,
                autocorrect: false,
                decoration: const InputDecoration(
                    labelText: 'Timezone', hintText: 'Europe/London', border: OutlineInputBorder()),
              ),
              const SizedBox(height: 16),
              Text('Name someone only when ${(_reveal * 100).round()}% sure',
                  style: const TextStyle(fontSize: 13)),
              // Below this confidence a guardian sees "someone" rather than
              // a name. Higher is safer for the people being watched.
              Slider(
                value: _reveal, min: 0.5, max: 1.0, divisions: 10,
                activeColor: NurbyColors.accent,
                onChanged: (v) => setState(() => _reveal = v),
              ),
              Row(
                children: [
                  const Expanded(child: Text('Cameras per person', style: TextStyle(fontSize: 13))),
                  IconButton(
                    icon: const Icon(Icons.remove, size: 18),
                    onPressed: _maxCams > 1 ? () => setState(() => _maxCams--) : null,
                  ),
                  Text('$_maxCams', style: const TextStyle(fontFamily: 'Menlo')),
                  IconButton(
                    icon: const Icon(Icons.add, size: 18),
                    onPressed: _maxCams < 1000 ? () => setState(() => _maxCams++) : null,
                  ),
                ],
              ),
              if (_error != null) ...[
                const SizedBox(height: 8),
                Text(_error!, style: const TextStyle(color: NurbyColors.danger, fontSize: 13)),
              ],
              const SizedBox(height: 16),
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
                  const SizedBox(width: 8),
                  FilledButton(
                      onPressed: _busy ? null : _save,
                      child: Text(widget.existing == null ? 'Create' : 'Save')),
                ],
              ),
            ],
          ),
        ),
      );
}
