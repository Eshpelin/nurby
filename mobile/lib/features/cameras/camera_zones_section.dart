import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import 'config_tiles.dart';

/// Privacy zones and saved PTZ positions for one camera (issue #162).
///
/// Privacy zones are the one setting here with real consequences if the
/// UI is careless. An auto-zone is drawn by the perception pipeline and
/// refreshed by it. Locking one stops that refresh, so a polygon someone
/// drew deliberately survives. Unlocking hands it back to the pipeline,
/// which will overwrite it. That has to be visible rather than a quiet
/// checkbox, so both states are labelled in words.
final privacyZonesProvider =
    FutureProvider.family<List<Map<String, dynamic>>, String>(
        (ref, cameraId) => ref.watch(privacyZoneRepoProvider).list(cameraId));

final privacyTargetsProvider = FutureProvider<List<String>>(
    (ref) => ref.watch(privacyZoneRepoProvider).targets());

final ptzPresetsProvider =
    FutureProvider.family<List<Map<String, dynamic>>, String>(
        (ref, cameraId) => ref.watch(ptzRepoProvider).presets(cameraId));

class CameraZonesSection extends ConsumerStatefulWidget {
  const CameraZonesSection({
    super.key,
    required this.cameraId,
    required this.raw,
    required this.isAdmin,
    required this.sectionLabel,
    required this.onPatch,
  });

  final String cameraId;
  final Map<String, dynamic> raw;
  final bool isAdmin;
  final Widget Function(String) sectionLabel;
  final Future<void> Function(Map<String, dynamic>) onPatch;

  @override
  ConsumerState<CameraZonesSection> createState() => _CameraZonesSectionState();
}

class _CameraZonesSectionState extends ConsumerState<CameraZonesSection> {
  Future<void> _zone(String zoneId, Map<String, dynamic> patch) async {
    try {
      await ref.read(privacyZoneRepoProvider).update(zoneId, patch);
      ref.invalidate(privacyZonesProvider(widget.cameraId));
    } catch (e) {
      _toast(apiErrorMessage(e));
    }
  }

  Future<void> _deleteZone(Map<String, dynamic> zone) async {
    final label = zone['label'] as String? ?? 'this zone';
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: NurbyColors.cardElevated,
        title: const Text('Delete privacy zone?'),
        // Deleting is not the same as switching off, and the difference
        // matters: an auto-zone the pipeline still recognises will simply
        // come back, while a hand-drawn one is gone for good.
        content: Text(zone['source'] == 'auto'
            ? '"$label" was detected automatically. Deleting it now will '
                'not stop it being detected again. Switch it off instead '
                'if you want it to stay off.'
            : '"$label" was drawn by hand and cannot be recovered.'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Cancel')),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Delete',
                style: TextStyle(color: NurbyColors.danger)),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await ref.read(privacyZoneRepoProvider).remove(zone['id'] as String);
      ref.invalidate(privacyZonesProvider(widget.cameraId));
    } catch (e) {
      _toast(apiErrorMessage(e));
    }
  }

  Future<void> _goto(String token, String name) async {
    try {
      await ref.read(ptzRepoProvider).goto(widget.cameraId, token);
      _toast('Moving to $name.');
    } catch (e) {
      _toast(apiErrorMessage(e));
    }
  }

  void _toast(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context) {
    final raw = widget.raw;
    final isAdmin = widget.isAdmin;
    final zones = ref.watch(privacyZonesProvider(widget.cameraId)).value ??
        const <Map<String, dynamic>>[];
    final targets = ref.watch(privacyTargetsProvider).value ?? const <String>[];
    final presets = ref.watch(ptzPresetsProvider(widget.cameraId)).value ??
        const <Map<String, dynamic>>[];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        widget.sectionLabel('PRIVACY'),
        Card(
          child: Column(children: [
            const Padding(
              padding: EdgeInsets.fromLTRB(16, 12, 16, 6),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('What to blur automatically',
                      style: TextStyle(fontSize: 14)),
                  SizedBox(height: 2),
                  Text(
                    'The pipeline draws a zone when it sees one of these.',
                    style: _sub,
                  ),
                ],
              ),
            ),
            _TargetPicker(
              available: targets,
              selected: (raw['privacy_zone_targets'] as List? ?? const [])
                  .map((t) => t.toString())
                  .toList(),
              enabled: isAdmin,
              onChanged: (v) => widget.onPatch({'privacy_zone_targets': v}),
            ),
            ConfigNumber(
              title: 'Blur strength',
              value: raw['privacy_zone_blur_strength'] as int? ?? 55,
              min: 5,
              max: 151,
              enabled: isAdmin,
              onChanged: (v) =>
                  widget.onPatch({'privacy_zone_blur_strength': v}),
            ),
            if (zones.isEmpty)
              const ListTile(
                dense: true,
                title: Text('No privacy zones on this camera',
                    style: TextStyle(fontSize: 13)),
                subtitle: Text(
                  'Zones appear here once the pipeline detects something '
                  'worth blurring, such as a neighbour\'s window.',
                  style: _sub,
                ),
              )
            else
              for (final z in zones) _ZoneTile(
                zone: z,
                enabled: isAdmin,
                onToggleActive: (v) => _zone(z['id'] as String, {'active': v}),
                onToggleLocked: (v) => _zone(z['id'] as String, {'locked': v}),
                onDelete: () => _deleteZone(z),
              ),
          ]),
        ),
        widget.sectionLabel('RETENTION'),
        Card(
          child: Column(children: [
            ConfigChoice<String>(
              title: 'Keep recordings',
              value: raw['retention_mode'] as String? ?? 'none',
              options: const ['none', 'time', 'size'],
              labels: const {
                'none': 'Forever',
                'time': 'For a number of days',
                'size': 'Up to a size limit',
              },
              enabled: isAdmin,
              onChanged: (v) => widget.onPatch({'retention_mode': v}),
            ),
            ConfigNumber(
              title: 'Keep for',
              value: raw['retention_days'] as int? ?? 30,
              min: 1,
              max: 3650,
              suffix: 'days',
              enabled: isAdmin && raw['retention_mode'] == 'time',
              onChanged: (v) => widget.onPatch({'retention_days': v}),
            ),
            ConfigNumber(
              title: 'Keep up to',
              // The server types this as a float. Whole gigabytes are the
              // only granularity anyone means, and JSON widens an int, so
              // this stays an integer control.
              value: (raw['retention_gb'] as num?)?.round() ?? 50,
              min: 1,
              max: 10000,
              suffix: 'GB',
              enabled: isAdmin && raw['retention_mode'] == 'size',
              onChanged: (v) => widget.onPatch({'retention_gb': v}),
            ),
            ConfigText(
              title: 'Timezone',
              value: raw['timezone'] as String?,
              placeholder: 'household default',
              hintText: 'Europe/London',
              maxLines: 1,
              maxLength: 64,
              enabled: isAdmin,
              onChanged: (v) => widget.onPatch({'timezone': v}),
            ),
            ConfigSwitch(
              title: 'Exclude from review',
              subtitle: 'Keeps this camera out of the review queue.',
              value: raw['exclude_from_review'] as bool? ?? false,
              enabled: isAdmin,
              onChanged: (v) => widget.onPatch({'exclude_from_review': v}),
            ),
          ]),
        ),
        if (presets.isNotEmpty) ...[
          widget.sectionLabel('SAVED POSITIONS'),
          Card(
            child: Column(children: [
              for (final p in presets)
                ListTile(
                  dense: true,
                  leading: const Icon(Icons.my_location,
                      size: 18, color: NurbyColors.mutedForeground),
                  title: Text('${p['name']}',
                      style: const TextStyle(fontSize: 13)),
                  trailing: const Icon(Icons.chevron_right,
                      size: 20, color: NurbyColors.mutedForeground),
                  onTap: () => _goto(
                      p['token'] as String, '${p['name']}'),
                ),
            ]),
          ),
        ],
      ],
    );
  }
}

class _ZoneTile extends StatelessWidget {
  const _ZoneTile({
    required this.zone,
    required this.enabled,
    required this.onToggleActive,
    required this.onToggleLocked,
    required this.onDelete,
  });

  final Map<String, dynamic> zone;
  final bool enabled;
  final ValueChanged<bool> onToggleActive;
  final ValueChanged<bool> onToggleLocked;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    final auto = zone['source'] == 'auto';
    final locked = zone['locked'] == true;
    final seen = zone['last_seen_at'] == null
        ? null
        : DateFormat('MMM d')
            .format(DateTime.parse('${zone['last_seen_at']}').toLocal());

    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 8, 8, 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(zone['label'] as String? ?? 'Unnamed zone',
                    style: const TextStyle(
                        fontSize: 13, fontWeight: FontWeight.w600)),
              ),
              Switch(
                value: zone['active'] == true,
                activeColor: NurbyColors.accent,
                onChanged: enabled ? onToggleActive : null,
              ),
              IconButton(
                icon: const Icon(Icons.delete_outline,
                    size: 18, color: NurbyColors.mutedForeground),
                onPressed: enabled ? onDelete : null,
              ),
            ],
          ),
          Text(
            [
              auto ? 'Detected automatically' : 'Drawn by hand',
              if (seen != null) 'last seen $seen',
            ].join(' · '),
            style: _sub,
          ),
          if (auto) ...[
            const SizedBox(height: 4),
            // The consequence, not the field name. "Locked" alone tells
            // nobody that unlocking lets the pipeline redraw their zone.
            InkWell(
              onTap: enabled ? () => onToggleLocked(!locked) : null,
              child: Row(
                children: [
                  Icon(locked ? Icons.lock_outline : Icons.lock_open,
                      size: 14,
                      color: locked
                          ? NurbyColors.accent
                          : NurbyColors.mutedForeground),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Text(
                      locked
                          ? 'Locked. The pipeline will not redraw this shape.'
                          : 'Unlocked. The pipeline may redraw this shape.',
                      style: _sub,
                    ),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// Targets are picked from the list the pipeline understands. Free text
/// would let someone enter a label that is silently never matched.
class _TargetPicker extends StatelessWidget {
  const _TargetPicker({
    required this.available,
    required this.selected,
    required this.enabled,
    required this.onChanged,
  });

  final List<String> available;
  final List<String> selected;
  final bool enabled;
  final ValueChanged<List<String>> onChanged;

  @override
  Widget build(BuildContext context) {
    if (available.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
      child: Wrap(
        spacing: 6,
        runSpacing: 6,
        children: [
          for (final t in available)
            FilterChip(
              label: Text(t, style: const TextStyle(fontSize: 12)),
              selected: selected.contains(t),
              onSelected: enabled
                  ? (on) {
                      final next = selected.where((x) => x != t).toList();
                      if (on) next.add(t);
                      onChanged(next);
                    }
                  : null,
            ),
        ],
      ),
    );
  }
}

const _sub = TextStyle(color: NurbyColors.mutedForeground, fontSize: 12);
