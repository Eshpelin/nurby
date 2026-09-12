import 'package:flutter_test/flutter_test.dart';
import 'package:nurby_mobile/features/cameras/zone_geometry.dart';

Set<Cell> _rect(int c0, int r0, int c1, int r1) => {
      for (var c = c0; c < c1; c++)
        for (var r = r0; r < r1; r++) (c, r),
    };

void main() {
  group('cellsToPolygons', () {
    test('one cell is a unit square in normalised coordinates', () {
      final polys = cellsToPolygons({(0, 0)}, cols: 4, rows: 4);
      expect(polys, hasLength(1));
      expect(polys.single, [
        [0.0, 0.0], [0.25, 0.0], [0.25, 0.25], [0.0, 0.25],
      ]);
    });

    test('a filled rectangle collapses to four corners', () {
      // Collinear points along the edges must be dropped, or a 4x3
      // block would come back as 14 points.
      final polys = cellsToPolygons(_rect(1, 1, 5, 4), cols: 8, rows: 8);
      expect(polys.single, hasLength(4));
      expect(polys.single, containsAll([[0.125, 0.125], [0.625, 0.5]]));
    });

    test('an L shape keeps its inner corner', () {
      final cells = _rect(0, 0, 3, 1)..addAll(_rect(0, 1, 1, 3));
      final polys = cellsToPolygons(cells, cols: 4, rows: 4);
      expect(polys.single, hasLength(6));
    });

    test('a ring becomes a solid polygon: holes are filled', () {
      final ring = _rect(0, 0, 4, 4)..removeAll(_rect(1, 1, 3, 3));
      final polys = cellsToPolygons(ring, cols: 4, rows: 4);
      // One polygon, the outer square. The hole is not a second polygon
      // and does not punch through.
      expect(polys, hasLength(1));
      expect(polys.single, hasLength(4));
    });

    test('two separate blobs are two polygons, largest first', () {
      final cells = _rect(0, 0, 1, 1)..addAll(_rect(2, 2, 4, 4));
      final polys = cellsToPolygons(cells, cols: 4, rows: 4);
      expect(polys, hasLength(2));
      expect(polys.first, hasLength(4));
      expect(polys.first, anyElement(equals([0.5, 0.5])));
    });

    test('diagonally touching cells are two regions, not a figure of eight',
        () {
      final polys = cellsToPolygons({(0, 0), (1, 1)}, cols: 4, rows: 4);
      expect(polys, hasLength(2));
    });

    test('empty input is no polygons', () {
      expect(cellsToPolygons(const {}), isEmpty);
    });
  });

  group('polygonToCells', () {
    test('rasterises a rectangle to the cells inside it', () {
      final cells = polygonToCells(
        [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]],
        cols: 4, rows: 4,
      );
      expect(cells, _rect(1, 1, 3, 3));
    });

    test('round-trips what cellsToPolygons produced', () {
      // The whole point: paint, save, reopen, see the same squares.
      final painted = _rect(2, 1, 6, 4)..addAll(_rect(2, 4, 3, 7));
      final polys = cellsToPolygons(painted, cols: 8, rows: 8);
      expect(polygonToCells(polys.single, cols: 8, rows: 8), painted);
    });

    test('a polygon thinner than a cell yields nothing rather than guessing',
        () {
      final cells = polygonToCells(
        [[0.0, 0.0], [0.01, 0.0], [0.01, 1.0], [0.0, 1.0]],
        cols: 4, rows: 4,
      );
      expect(cells, isEmpty);
    });

    test('fewer than three points is not a polygon', () {
      expect(polygonToCells([[0, 0], [1, 1]]), isEmpty);
    });
  });

  group('connectedRegions', () {
    test('counts blobs by edge adjacency', () {
      expect(connectedRegions({(0, 0), (1, 0), (3, 3)}), 2);
      expect(connectedRegions({(0, 0), (1, 1)}), 2);
      expect(connectedRegions(const {}), 0);
    });
  });

  group('tripwire helpers', () {
    test('snaps a touch to the nearest grid corner', () {
      expect(snapToCorner(0.26, 0.74, cols: 4, rows: 4), [0.25, 0.75]);
      expect(snapToCorner(1.2, -0.1, cols: 4, rows: 4), [1.0, 0.0]);
    });

    test('distance to a segment', () {
      expect(distanceToSegment(0.5, 0.5, [0, 0.5], [1, 0.5]), closeTo(0, 1e-9));
      expect(distanceToSegment(0.5, 0.0, [0, 0.5], [1, 0.5]), closeTo(0.5, 1e-9));
      expect(distanceToSegment(2.0, 0.5, [0, 0.5], [1, 0.5]), closeTo(1.0, 1e-9));
    });
  });
}
