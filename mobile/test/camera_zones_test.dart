import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:nurby_mobile/features/cameras/camera_zones_section.dart';

Map<String, dynamic> _zone({
  String source = 'auto',
  bool active = true,
  bool locked = false,
  String label = 'Neighbour window',
}) =>
    {
      'id': 'z1',
      'camera_id': 'c1',
      'label': label,
      'polygon': [
        [0.1, 0.1],
        [0.3, 0.1],
        [0.3, 0.4]
      ],
      'source': source,
      'active': active,
      'locked': locked,
      'last_seen_at': '2026-09-08T10:00:00Z',
    };

Future<void> _pump(
  WidgetTester tester, {
  List<Map<String, dynamic>> zones = const [],
  List<String> targets = const [],
  List<Map<String, dynamic>> presets = const [],
  Map<String, dynamic>? raw,
  bool isAdmin = true,
  void Function(Map<String, dynamic>)? onPatch,
}) async {
  await tester.pumpWidget(ProviderScope(
    overrides: [
      privacyZonesProvider('c1').overrideWith((ref) async => zones),
      privacyTargetsProvider.overrideWith((ref) async => targets),
      ptzPresetsProvider('c1').overrideWith((ref) async => presets),
    ],
    child: MaterialApp(
      home: Scaffold(
        body: ListView(children: [
          CameraZonesSection(
            cameraId: 'c1',
            raw: raw ?? {'retention_mode': 'none'},
            isAdmin: isAdmin,
            sectionLabel: (t) => Text(t),
            onPatch: (p) async => onPatch?.call(p),
          ),
        ]),
      ),
    ),
  ));
  await tester.pumpAndSettle();
}

void main() {
  group('privacy zones', () {
    // "Locked" as a bare label tells nobody that unlocking hands the
    // polygon back to the pipeline to redraw. The consequence is the part
    // worth showing, so both states are asserted.
    testWidgets('an unlocked auto zone says the pipeline may redraw it',
        (tester) async {
      await _pump(tester, zones: [_zone(locked: false)]);
      expect(find.text('Unlocked. The pipeline may redraw this shape.'),
          findsOneWidget);
    });

    testWidgets('a locked auto zone says the pipeline will not',
        (tester) async {
      await _pump(tester, zones: [_zone(locked: true)]);
      expect(find.text('Locked. The pipeline will not redraw this shape.'),
          findsOneWidget);
    });

    testWidgets('a hand-drawn zone has no lock control at all',
        (tester) async {
      // Locking only means something against the auto refresh. Offering
      // it on a hand-drawn zone would imply a threat that does not exist.
      await _pump(tester, zones: [_zone(source: 'manual')]);
      expect(find.textContaining('redraw this shape'), findsNothing);
      expect(find.text('Drawn by hand · last seen Sep 8'), findsOneWidget);
    });

    testWidgets('deleting an auto zone warns that it will come back',
        (tester) async {
      await _pump(tester, zones: [_zone(source: 'auto')]);
      await tester.tap(find.byIcon(Icons.delete_outline));
      await tester.pumpAndSettle();
      expect(find.textContaining('will not stop it being detected again'),
          findsOneWidget);
    });

    testWidgets('deleting a hand-drawn zone warns it cannot be recovered',
        (tester) async {
      await _pump(tester, zones: [_zone(source: 'manual')]);
      await tester.tap(find.byIcon(Icons.delete_outline));
      await tester.pumpAndSettle();
      expect(find.textContaining('cannot be recovered'), findsOneWidget);
    });

    testWidgets('says plainly when a camera has no zones', (tester) async {
      await _pump(tester);
      expect(find.text('No blur areas on this camera'), findsOneWidget);
    });

    testWidgets('a non-admin sees zone state but cannot change it',
        (tester) async {
      await _pump(tester, zones: [_zone(active: true)], isAdmin: false);
      final sw = tester.widget<Switch>(find.byType(Switch).first);
      expect(sw.value, isTrue);
      expect(sw.onChanged, isNull);
    });
  });

  group('privacy targets', () {
    testWidgets('offers only labels the pipeline understands',
        (tester) async {
      // Free text here would let someone save a target that is silently
      // never matched, and the camera would look configured when it was
      // not.
      await _pump(tester,
          targets: const ['person', 'tv', 'laptop'],
          raw: {'retention_mode': 'none', 'privacy_zone_targets': ['tv']});
      expect(find.widgetWithText(FilterChip, 'person'), findsOneWidget);
      expect(find.widgetWithText(FilterChip, 'tv'), findsOneWidget);
      final chip = tester.widget<FilterChip>(
          find.widgetWithText(FilterChip, 'tv'));
      expect(chip.selected, isTrue);
    });

    testWidgets('selecting a target sends the whole list', (tester) async {
      Map<String, dynamic>? patch;
      await _pump(tester,
          targets: const ['person', 'tv'],
          raw: {'retention_mode': 'none', 'privacy_zone_targets': ['tv']},
          onPatch: (p) => patch = p);

      await tester.tap(find.widgetWithText(FilterChip, 'person'));
      await tester.pumpAndSettle();
      expect(patch, {'privacy_zone_targets': ['tv', 'person']});
    });
  });

  group('retention', () {
    testWidgets('day and size limits follow the mode', (tester) async {
      await _pump(tester, raw: {'retention_mode': 'time', 'retention_days': 14});
      // "Keep for" is live in time mode, "Keep up to" is not.
      expect(find.text('14 days'), findsOneWidget);
      final tiles = tester
          .widgetList<ListTile>(find.byType(ListTile))
          .where((t) => t.title is Text)
          .toList();
      final keepUpTo = tiles.firstWhere(
          (t) => (t.title as Text).data == 'Keep up to');
      expect(keepUpTo.enabled, isFalse);
    });

    testWidgets('a float size limit renders as whole gigabytes',
        (tester) async {
      // The server types retention_gb as a number. 50.0 must not reach
      // the user as "50.0 GB".
      await _pump(tester,
          raw: {'retention_mode': 'size', 'retention_gb': 50.0});
      expect(find.text('50 GB'), findsOneWidget);
    });
  });

  group('PTZ presets', () {
    testWidgets('the section is absent when a camera has no presets',
        (tester) async {
      await _pump(tester);
      expect(find.text('SAVED POSITIONS'), findsNothing);
    });

    testWidgets('lists saved positions by name', (tester) async {
      await _pump(tester, presets: [
        {'token': 't1', 'name': 'Front gate'},
        {'token': 't2', 'name': 'Driveway'},
      ]);
      expect(find.text('SAVED POSITIONS'), findsOneWidget);
      expect(find.text('Front gate'), findsOneWidget);
      expect(find.text('Driveway'), findsOneWidget);
    });
  });
}
