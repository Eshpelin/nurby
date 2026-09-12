import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../models/models.dart';
import 'live_view.dart';
import 'motion_zones_section.dart' show zoneColor, kZoneTypeLabels;
import 'zone_geometry.dart';

/// Draw a motion zone or tripwire over the live view (#182).
///
/// Zones are painted: a 16 by 9 grid of squares over the video, filled
/// or cleared with a fingertip, dragged to paint a run. Tripwires are
/// two taps on grid corners plus a direction. On save the grid becomes
/// a polygon (see zone_geometry.dart); on open a polygon becomes squares.
///
/// The live view underneath moves. That is the point: you draw over
/// what the camera sees right now, not a still that may be stale. The
/// grid tints what it covers so the effect of the zone is visible while
/// drawing, not only after it fires.
class ZoneEditorScreen extends ConsumerStatefulWidget {
  const ZoneEditorScreen({
    super.key,
    required this.camera,
    required this.zones,
    this.editIndex,
  });

  final Camera camera;

  /// All zones on the camera. The edited one is replaced in place; new
  /// ones are appended. The whole list is what gets PATCHed.
  final List<Map<String, dynamic>> zones;
  final int? editIndex;

  @override
  ConsumerState<ZoneEditorScreen> createState() => _ZoneEditorScreenState();
}

class _ZoneEditorScreenState extends ConsumerState<ZoneEditorScreen> {
  late final _name = TextEditingController(
      text: widget.editIndex == null ? '' : '${widget.zones[widget.editIndex!]['name'] ?? ''}');
  late String _type = widget.editIndex == null
      ? 'zone'
      : (widget.zones[widget.editIndex!]['type'] as String? ?? 'zone');
  late final Set<Cell> _cells = _initialCells();
  late List<List<double>> _line = _initialLine();
  late String _direction = widget.editIndex == null
      ? 'any'
      : (widget.zones[widget.editIndex!]['direction'] as String? ?? 'any');
  late int _loiterSeconds = widget.editIndex == null
      ? 30
      : ((widget.zones[widget.editIndex!]['loiter_threshold_seconds'] as num?)?.toInt() ?? 30);
  bool? _paintingOn; // set on drag start: paint or erase for the whole stroke
  bool _busy = false;

  bool get _isTripwire => _type == 'tripwire';

  Set<Cell> _initialCells() {
    if (widget.editIndex == null) return {};
    final z = widget.zones[widget.editIndex!];
    if (z['type'] == 'tripwire') return {};
    final pts = (z['points'] as List? ?? const [])
        .whereType<List>()
        .map((p) => [(p[0] as num).toDouble(), (p[1] as num).toDouble()])
        .toList();
    return polygonToCells(pts);
  }

  List<List<double>> _initialLine() {
    if (widget.editIndex == null) return [];
    final z = widget.zones[widget.editIndex!];
    if (z['type'] != 'tripwire') return [];
    return (z['points'] as List? ?? const [])
        .whereType<List>()
        .take(2)
        .map((p) => [(p[0] as num).toDouble(), (p[1] as num).toDouble()])
        .toList();
  }

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  // ---- gestures ----

  Cell? _cellAt(Offset local, Size size) {
    final c = (local.dx / size.width * kZoneGridCols).floor();
    final r = (local.dy / size.height * kZoneGridRows).floor();
    if (c < 0 || r < 0 || c >= kZoneGridCols || r >= kZoneGridRows) return null;
    return (c, r);
  }

  void _touch(Offset local, Size size, {required bool start}) {
    if (_isTripwire) {
      if (!start) return;
      final p = snapToCorner(local.dx / size.width, local.dy / size.height);
      setState(() {
        // Third tap starts over. Two points is a line; there is no
        // third to add.
        _line = _line.length >= 2 ? [p] : [..._line, p];
      });
      return;
    }
    final cell = _cellAt(local, size);
    if (cell == null) return;
    setState(() {
      // A stroke either paints or erases, decided by the first cell it
      // touches. Otherwise dragging across a half-filled area flickers.
      _paintingOn ??= !_cells.contains(cell);
      if (_paintingOn!) {
        _cells.add(cell);
      } else {
        _cells.remove(cell);
      }
    });
  }

  // ---- save ----

  bool get _canSave => _isTripwire ? _line.length == 2 : _cells.isNotEmpty;

  Future<void> _save() async {
    final name = _name.text.trim().isEmpty ? _defaultName() : _name.text.trim();
    final next = [...widget.zones];
    final built = <Map<String, dynamic>>[];

    if (_isTripwire) {
      built.add({
        'name': name,
        'type': 'tripwire',
        'points': _line,
        'direction': _direction,
      });
    } else {
      final polys = cellsToPolygons(_cells);
      for (var i = 0; i < polys.length; i++) {
        built.add({
          // Two separate blobs painted under one name become two zones,
          // numbered, rather than one being silently dropped.
          'name': polys.length == 1 ? name : '$name ${i + 1}',
          'type': _type,
          'points': polys[i],
          if (_type == 'loiter') 'loiter_threshold_seconds': _loiterSeconds,
        });
      }
    }

    if (widget.editIndex != null) {
      next.removeAt(widget.editIndex!);
      next.insertAll(widget.editIndex!, built);
    } else {
      next.addAll(built);
    }

    setState(() => _busy = true);
    try {
      await ref.read(cameraRepoProvider).update(widget.camera.id, {'motion_zones': next});
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  String _defaultName() {
    final base = kZoneTypeLabels[_type] ?? 'Zone';
    final n = widget.zones.where((z) => z['type'] == _type).length + 1;
    return '$base $n';
  }

  @override
  Widget build(BuildContext context) {
    final color = zoneColor(_type);

    return Scaffold(
      appBar: AppBar(
        title: Text(widget.editIndex == null ? 'New zone' : 'Edit zone'),
        actions: [
          TextButton(
            onPressed: _busy || !_canSave ? null : _save,
            child: const Text('Save'),
          ),
        ],
      ),
      body: ListView(
        children: [
          // The canvas. GestureDetector on top of the live view; the
          // painter draws the grid, the filled cells and the tripwire.
          AspectRatio(
            aspectRatio: 16 / 9,
            child: LayoutBuilder(
              builder: (context, box) {
                final size = Size(box.maxWidth, box.maxHeight);
                return GestureDetector(
                  onPanStart: (d) => _touch(d.localPosition, size, start: true),
                  onPanUpdate: (d) => _touch(d.localPosition, size, start: false),
                  onPanEnd: (_) => _paintingOn = null,
                  onPanCancel: () => _paintingOn = null,
                  child: Stack(
                    fit: StackFit.expand,
                    children: [
                      CameraLiveView(camera: widget.camera),
                      IgnorePointer(
                        child: CustomPaint(
                          painter: _GridPainter(
                            cells: _cells,
                            line: _line,
                            color: color,
                            tripwire: _isTripwire,
                            direction: _direction,
                          ),
                        ),
                      ),
                    ],
                  ),
                );
              },
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
            child: Text(
              _isTripwire
                  ? (_line.length < 2
                      ? 'Tap two points on the video to draw the line.'
                      : 'Tap again to start over.')
                  : 'Drag across the squares to fill them. Drag over filled squares to clear.',
              style: const TextStyle(fontSize: 12, color: NurbyColors.mutedForeground),
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 12, 12, 0),
            child: Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                for (final t in ['zone', 'include', 'exclude', 'loiter', 'tripwire'])
                  ChoiceChip(
                    avatar: CircleAvatar(backgroundColor: zoneColor(t), radius: 5),
                    label: Text(kZoneTypeLabels[t]!, style: const TextStyle(fontSize: 12)),
                    selected: _type == t,
                    onSelected: (_) => setState(() => _type = t),
                  ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 4, 12, 0),
            child: Text(
              switch (_type) {
                'include' => 'Only motion inside counts. Everything else on this camera is ignored.',
                'exclude' => 'Motion inside is ignored. A road, a tree, a neighbour\'s drive.',
                'loiter' => 'Fires when someone stays inside for longer than the threshold.',
                'tripwire' => 'Fires when something crosses the line.',
                _ => 'A named area rules can refer to.',
              },
              style: const TextStyle(fontSize: 12, color: NurbyColors.mutedForeground),
            ),
          ),
          if (_type == 'loiter')
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
              child: Row(
                children: [
                  const Text('After', style: TextStyle(fontSize: 13)),
                  Expanded(
                    child: Slider(
                      value: _loiterSeconds.toDouble(),
                      min: 5, max: 600, divisions: 119,
                      activeColor: NurbyColors.accent,
                      label: '${_loiterSeconds}s',
                      onChanged: (v) => setState(() => _loiterSeconds = v.round()),
                    ),
                  ),
                  SizedBox(width: 44, child: Text('${_loiterSeconds}s', style: const TextStyle(fontFamily: 'Menlo', fontSize: 12))),
                ],
              ),
            ),
          if (_isTripwire)
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
              child: Wrap(
                spacing: 6,
                children: [
                  for (final (d, label) in [('any', 'Either way'), ('in', 'Crossing in'), ('out', 'Crossing out')])
                    ChoiceChip(
                      label: Text(label, style: const TextStyle(fontSize: 12)),
                      selected: _direction == d,
                      onSelected: (_) => setState(() => _direction = d),
                    ),
                ],
              ),
            ),
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 12, 12, 24),
            child: TextField(
              controller: _name,
              decoration: InputDecoration(
                labelText: 'Name',
                hintText: _defaultName(),
                border: const OutlineInputBorder(),
                isDense: true,
              ),
            ),
          ),
          if (!_isTripwire && connectedRegions(_cells) > 1)
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 0, 12, 24),
              child: Text(
                'You have painted ${connectedRegions(_cells)} separate areas. '
                'They will be saved as ${connectedRegions(_cells)} zones, numbered.',
                style: const TextStyle(fontSize: 12, color: NurbyColors.warning),
              ),
            ),
        ],
      ),
    );
  }
}

class _GridPainter extends CustomPainter {
  _GridPainter({
    required this.cells,
    required this.line,
    required this.color,
    required this.tripwire,
    required this.direction,
  });

  final Set<Cell> cells;
  final List<List<double>> line;
  final Color color;
  final bool tripwire;
  final String direction;

  @override
  void paint(Canvas canvas, Size size) {
    final cw = size.width / kZoneGridCols;
    final ch = size.height / kZoneGridRows;

    // Faint grid so the squares are visible before anything is painted.
    final grid = Paint()
      ..color = Colors.white.withValues(alpha: 0.18)
      ..strokeWidth = 1;
    for (var c = 1; c < kZoneGridCols; c++) {
      canvas.drawLine(Offset(c * cw, 0), Offset(c * cw, size.height), grid);
    }
    for (var r = 1; r < kZoneGridRows; r++) {
      canvas.drawLine(Offset(0, r * ch), Offset(size.width, r * ch), grid);
    }

    if (!tripwire) {
      final fill = Paint()..color = color.withValues(alpha: 0.38);
      final edge = Paint()
        ..color = color
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.5;
      for (final (c, r) in cells) {
        final rect = Rect.fromLTWH(c * cw, r * ch, cw, ch);
        canvas.drawRect(rect, fill);
        canvas.drawRect(rect.deflate(0.5), edge);
      }
      return;
    }

    final dot = Paint()..color = color;
    for (final p in line) {
      canvas.drawCircle(Offset(p[0] * size.width, p[1] * size.height), 7, dot);
    }
    if (line.length == 2) {
      final a = Offset(line[0][0] * size.width, line[0][1] * size.height);
      final b = Offset(line[1][0] * size.width, line[1][1] * size.height);
      canvas.drawLine(a, b, Paint()
        ..color = color
        ..strokeWidth = 4
        ..strokeCap = StrokeCap.round);
      // Direction: a short tick perpendicular to the line, on the side
      // the crossing must come from. Nothing for "any".
      if (direction != 'any') {
        final mid = (a + b) / 2;
        final d = b - a;
        final n = Offset(-d.dy, d.dx) / d.distance * 18 * (direction == 'in' ? 1 : -1);
        canvas.drawLine(mid, mid + n, Paint()
          ..color = color
          ..strokeWidth = 3
          ..strokeCap = StrokeCap.round);
        canvas.drawCircle(mid + n, 4, dot);
      }
    }
  }

  @override
  bool shouldRepaint(_GridPainter old) =>
      old.cells != cells || old.line != line || old.color != color ||
      old.tripwire != tripwire || old.direction != direction;
}
