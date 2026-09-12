/// Grid-painted zones and their polygon form (#182).
///
/// The backend stores a motion zone as a polygon of normalised points.
/// The phone edits it as a grid of squares you fill with a fingertip.
/// These two functions convert between them, and are pure so the
/// conversion can be pinned by tests rather than by eye.
///
/// One rule from the conversion: holes are filled. A ring of squares
/// with an empty middle becomes a solid polygon, because a zone with a
/// hole in it is two zones' worth of surprise for one name.
library;

import 'dart:math' as math;

/// Grid size. 16 by 9 matches the frame's aspect, so every cell is a
/// square, and on a phone each cell is about the size of a fingertip.
const kZoneGridCols = 16;
const kZoneGridRows = 9;

/// A cell, column then row, both zero-based.
typedef Cell = (int, int);

/// A polygon as normalised `[x, y]` pairs, the backend's shape.
typedef Polygon = List<List<double>>;

/// Rasterise a polygon: the set of cells whose centre lies inside it.
///
/// Ray casting on the cell centre. A zone thinner than a cell can
/// vanish, which is the honest result: the grid cannot represent it
/// and saying so beats inventing cells.
Set<Cell> polygonToCells(Polygon poly,
    {int cols = kZoneGridCols, int rows = kZoneGridRows}) {
  if (poly.length < 3) return const {};
  final out = <Cell>{};
  for (var r = 0; r < rows; r++) {
    for (var c = 0; c < cols; c++) {
      final x = (c + 0.5) / cols;
      final y = (r + 0.5) / rows;
      if (_inside(x, y, poly)) out.add((c, r));
    }
  }
  return out;
}

bool _inside(double x, double y, Polygon poly) {
  var inside = false;
  for (var i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    final xi = poly[i][0], yi = poly[i][1];
    final xj = poly[j][0], yj = poly[j][1];
    final crosses = (yi > y) != (yj > y) &&
        x < (xj - xi) * (y - yi) / ((yj - yi) == 0 ? 1e-12 : (yj - yi)) + xi;
    if (crosses) inside = !inside;
  }
  return inside;
}

/// Trace painted cells into polygons, one per connected region.
///
/// Every cell contributes four clockwise edges. An edge shared by two
/// cells appears twice in opposite directions and cancels. What is left
/// is the boundary: outer loops run clockwise, holes anticlockwise. Holes
/// are dropped, collinear points are merged, and each loop comes back as
/// normalised points. Two separate blobs give two polygons, so the
/// caller can name them "Drive 1" and "Drive 2" rather than lose one.
List<Polygon> cellsToPolygons(Set<Cell> cells,
    {int cols = kZoneGridCols, int rows = kZoneGridRows}) {
  if (cells.isEmpty) return const [];

  // Directed edges keyed by (from, to) in grid-corner coordinates.
  final edges = <_Pt, List<_Pt>>{};
  void add(_Pt a, _Pt b) => (edges[a] ??= []).add(b);
  void cancelOrAdd(_Pt a, _Pt b) {
    final rev = edges[b];
    if (rev != null && rev.remove(a)) {
      if (rev.isEmpty) edges.remove(b);
      return;
    }
    add(a, b);
  }

  for (final (c, r) in cells) {
    final tl = _Pt(c, r), tr = _Pt(c + 1, r);
    final br = _Pt(c + 1, r + 1), bl = _Pt(c, r + 1);
    cancelOrAdd(tl, tr);
    cancelOrAdd(tr, br);
    cancelOrAdd(br, bl);
    cancelOrAdd(bl, tl);
  }

  // Chain edges into loops. Where two loops touch at a corner there are
  // two outgoing edges; prefer the one that turns right (keeps to the
  // outside), which is what makes diagonally touching cells trace as
  // two separate regions rather than one figure of eight.
  final loops = <List<_Pt>>[];
  while (edges.isNotEmpty) {
    final start = edges.keys.first;
    final loop = <_Pt>[start];
    var cur = start;
    _Pt? prev;
    while (true) {
      final outs = edges[cur];
      if (outs == null || outs.isEmpty) break;
      _Pt next;
      if (outs.length == 1 || prev == null) {
        next = outs.first;
      } else {
        next = outs.reduce((a, b) => _turn(prev!, cur, a) > _turn(prev, cur, b) ? a : b);
      }
      outs.remove(next);
      if (outs.isEmpty) edges.remove(cur);
      if (next == start) break;
      loop.add(next);
      prev = cur;
      cur = next;
    }
    if (loop.length >= 4) loops.add(loop);
  }

  // Outer boundaries traced clockwise in a y-down grid have positive
  // signed area with this formula; holes come out negative and are dropped.
  final out = <Polygon>[];
  for (final loop in loops) {
    if (_signedArea(loop) <= 0) continue;
    final simplified = _dropCollinear(loop);
    out.add([
      for (final p in simplified) [p.x / cols, p.y / rows],
    ]);
  }
  // Largest first, so the primary region keeps the plain name.
  out.sort((a, b) => _polyArea(b).compareTo(_polyArea(a)));
  return out;
}

/// Cross product of the turn prev -> cur -> next. In y-down screen
/// coordinates a positive value is a right turn, which is the one that
/// keeps a clockwise trace on the outside of the region.
double _turn(_Pt prev, _Pt cur, _Pt next) {
  final ax = cur.x - prev.x, ay = cur.y - prev.y;
  final bx = next.x - cur.x, by = next.y - cur.y;
  return (ax * by - ay * bx).toDouble();
}

double _signedArea(List<_Pt> loop) {
  var a = 0.0;
  for (var i = 0; i < loop.length; i++) {
    final p = loop[i], q = loop[(i + 1) % loop.length];
    a += (p.x * q.y - q.x * p.y);
  }
  return a / 2;
}

double _polyArea(Polygon poly) {
  var a = 0.0;
  for (var i = 0; i < poly.length; i++) {
    final p = poly[i], q = poly[(i + 1) % poly.length];
    a += (p[0] * q[1] - q[0] * p[1]);
  }
  return a.abs() / 2;
}

List<_Pt> _dropCollinear(List<_Pt> loop) {
  final out = <_Pt>[];
  for (var i = 0; i < loop.length; i++) {
    final prev = loop[(i - 1 + loop.length) % loop.length];
    final cur = loop[i];
    final next = loop[(i + 1) % loop.length];
    if (_turn(prev, cur, next) != 0) out.add(cur);
  }
  return out;
}

/// Cells reachable from each other by edge adjacency, for naming the
/// second and third blob of one paint session. Pure.
int connectedRegions(Set<Cell> cells) {
  final seen = <Cell>{};
  var n = 0;
  for (final start in cells) {
    if (seen.contains(start)) continue;
    n++;
    final stack = [start];
    while (stack.isNotEmpty) {
      final (c, r) = stack.removeLast();
      if (!seen.add((c, r))) continue;
      for (final nb in [(c + 1, r), (c - 1, r), (c, r + 1), (c, r - 1)]) {
        if (cells.contains(nb) && !seen.contains(nb)) stack.add(nb);
      }
    }
  }
  return n;
}

/// A tripwire is two points, not cells. Snap a touch to the nearest grid
/// corner so a line drawn by hand lands on the same lattice the zones
/// use. Pure.
List<double> snapToCorner(double x, double y,
    {int cols = kZoneGridCols, int rows = kZoneGridRows}) {
  final cx = (x * cols).round().clamp(0, cols) / cols;
  final cy = (y * rows).round().clamp(0, rows) / rows;
  return [cx, cy];
}

/// Distance from a point to a segment, for hit-testing a tripwire. Pure.
double distanceToSegment(double px, double py, List<double> a, List<double> b) {
  final dx = b[0] - a[0], dy = b[1] - a[1];
  final len2 = dx * dx + dy * dy;
  if (len2 == 0) return math.sqrt(math.pow(px - a[0], 2) + math.pow(py - a[1], 2));
  final t = (((px - a[0]) * dx + (py - a[1]) * dy) / len2).clamp(0.0, 1.0);
  final x = a[0] + t * dx, y = a[1] + t * dy;
  return math.sqrt(math.pow(px - x, 2) + math.pow(py - y, 2));
}

class _Pt {
  const _Pt(this.x, this.y);
  final int x;
  final int y;

  @override
  bool operator ==(Object o) => o is _Pt && o.x == x && o.y == y;

  @override
  int get hashCode => Object.hash(x, y);
}
