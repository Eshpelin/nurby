import 'package:flutter/material.dart';

import '../../core/theme.dart';

/// Motion zones and tripwires, read-only plus remove (#182, first slice).
///
/// Drawing a zone with a finger needs a design pass (see the issue).
/// Seeing the zones drawn on web, over the actual frame, and removing
/// one that is wrong is a fraction of the work and most of the value:
/// nothing here can make a zone worse.
///
/// Points are stored normalised (0 to 1), so they scale to whatever the
/// frame is displayed at.

/// The zone types the pipeline knows, and how each reads.
const kZoneTypeLabels = {
  'zone': 'Zone',
  'include': 'Only alert here',
  'exclude': 'Ignore here',
  'loiter': 'Loitering',
  'tripwire': 'Tripwire',
  'veto': 'Veto',
  'signal': 'Traffic signal',
};

String zoneTypeLabel(String? type) => kZoneTypeLabels[type] ?? (type ?? 'Zone');

/// Colour per type, so a tripwire does not look like an exclusion. Pure.
Color zoneColor(String? type) => switch (type) {
      'exclude' || 'veto' => NurbyColors.danger,
      'tripwire' => NurbyColors.warning,
      'loiter' => Colors.purpleAccent,
      'signal' => Colors.lightBlueAccent,
      _ => NurbyColors.accent,
    };

class MotionZonesSection extends StatelessWidget {
  const MotionZonesSection({
    super.key,
    required this.zones,
    required this.frameUrl,
    required this.isAdmin,
    required this.sectionLabel,
    required this.onPatch,
  });

  final List<Map<String, dynamic>> zones;
  final String frameUrl;
  final bool isAdmin;
  final Widget Function(String) sectionLabel;
  final Future<void> Function(Map<String, dynamic>) onPatch;

  Future<void> _remove(BuildContext context, int index) async {
    final z = zones[index];
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: NurbyColors.cardElevated,
        title: Text('Remove "${z['name'] ?? 'this zone'}"?'),
        // What removing it does to alerting, per type. "Are you sure" is
        // not enough for a change that quietly stops or starts alerts.
        content: Text(switch (z['type']) {
          'exclude' => 'Motion inside it will start counting again.',
          'include' => 'Motion anywhere on the camera will count, not just here.',
          'tripwire' => 'Crossings here will no longer be detected.',
          'loiter' => 'Lingering here will no longer be detected.',
          _ => 'Rules that mention this zone will stop matching it.',
        }),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Cancel')),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Remove',
                style: TextStyle(color: NurbyColors.danger)),
          ),
        ],
      ),
    );
    if (ok != true) return;
    final next = [...zones]..removeAt(index);
    await onPatch({'motion_zones': next});
  }

  @override
  Widget build(BuildContext context) {
    if (zones.isEmpty) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        sectionLabel('ZONES AND TRIPWIRES'),
        Card(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              ClipRRect(
                borderRadius:
                    const BorderRadius.vertical(top: Radius.circular(12)),
                child: AspectRatio(
                  aspectRatio: 16 / 9,
                  child: Stack(
                    fit: StackFit.expand,
                    children: [
                      Image.network(
                        frameUrl,
                        fit: BoxFit.cover,
                        errorBuilder: (_, __, ___) =>
                            const ColoredBox(color: NurbyColors.cardElevated),
                      ),
                      CustomPaint(painter: _ZonesPainter(zones)),
                    ],
                  ),
                ),
              ),
              for (var i = 0; i < zones.length; i++)
                ListTile(
                  dense: true,
                  leading: Container(
                    width: 12,
                    height: 12,
                    decoration: BoxDecoration(
                      color: zoneColor(zones[i]['type'] as String?),
                      shape: zones[i]['type'] == 'tripwire'
                          ? BoxShape.rectangle
                          : BoxShape.circle,
                    ),
                  ),
                  title: Text('${zones[i]['name'] ?? 'Zone ${i + 1}'}',
                      style: const TextStyle(fontSize: 13)),
                  subtitle: Text(
                    [
                      zoneTypeLabel(zones[i]['type'] as String?),
                      '${(zones[i]['points'] as List? ?? const []).length} points',
                      if (zones[i]['type'] == 'loiter' &&
                          zones[i]['loiter_threshold_seconds'] != null)
                        'after ${zones[i]['loiter_threshold_seconds']}s',
                      if (zones[i]['type'] == 'tripwire' &&
                          zones[i]['direction'] != null &&
                          zones[i]['direction'] != 'any')
                        'direction ${zones[i]['direction']}',
                    ].join(' · '),
                    style: const TextStyle(
                        fontSize: 11, color: NurbyColors.mutedForeground),
                  ),
                  trailing: isAdmin
                      ? IconButton(
                          icon: const Icon(Icons.delete_outline, size: 18),
                          onPressed: () => _remove(context, i),
                        )
                      : null,
                ),
              const Padding(
                padding: EdgeInsets.fromLTRB(16, 0, 16, 12),
                child: Text(
                  'Zones are drawn on the web app. Here you can see them and remove one.',
                  style: TextStyle(
                      fontSize: 11, color: NurbyColors.mutedForeground),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _ZonesPainter extends CustomPainter {
  _ZonesPainter(this.zones);
  final List<Map<String, dynamic>> zones;

  @override
  void paint(Canvas canvas, Size size) {
    for (final z in zones) {
      final pts = (z['points'] as List? ?? const [])
          .whereType<List>()
          .where((p) => p.length >= 2)
          .map((p) => Offset(
                (p[0] as num).toDouble() * size.width,
                (p[1] as num).toDouble() * size.height,
              ))
          .toList();
      if (pts.length < 2) continue;
      final color = zoneColor(z['type'] as String?);
      final path = Path()..moveTo(pts.first.dx, pts.first.dy);
      for (final p in pts.skip(1)) {
        path.lineTo(p.dx, p.dy);
      }
      if (z['type'] == 'tripwire') {
        canvas.drawPath(
            path,
            Paint()
              ..color = color
              ..style = PaintingStyle.stroke
              ..strokeWidth = 3);
      } else {
        path.close();
        canvas.drawPath(path, Paint()..color = color.withValues(alpha: 0.22));
        canvas.drawPath(
            path,
            Paint()
              ..color = color
              ..style = PaintingStyle.stroke
              ..strokeWidth = 2);
      }
    }
  }

  @override
  bool shouldRepaint(_ZonesPainter old) => old.zones != zones;
}
