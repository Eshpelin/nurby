import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nurby_mobile/features/cameras/add_camera_sheet.dart';
import 'package:nurby_mobile/features/cameras/cameras_screen.dart';

Map<String, dynamic> _device({
  String manufacturer = 'Hikvision',
  String model = 'DS-2CD2043',
  String name = 'IPCamera',
  bool alreadyAdded = false,
  bool authRequired = true,
  String resolution = '1920x1080',
}) =>
    {
      'ip': '192.168.1.64',
      'port': 80,
      'name': name,
      'manufacturer': manufacturer,
      'model': model,
      'firmware': 'V5.5.0',
      'onvif_url': 'http://192.168.1.64/onvif/device_service',
      'stream_url': 'rtsp://192.168.1.64:554/Streaming/Channels/101',
      'profiles': const [],
      'auth_required': authRequired,
      'resolution': resolution,
      'already_added': alreadyAdded,
    };

Widget _wrap(Widget child) =>
    MaterialApp(home: Scaffold(body: ListView(children: [child])));

void main() {
  group('discoveredTitle', () {
    test('prefers manufacturer and model over the ONVIF name', () {
      // Most cameras report a name like "IPCamera", which tells a
      // household nothing when three of them answer the scan.
      expect(discoveredTitle(_device()), 'Hikvision DS-2CD2043');
    });

    test('falls back to the reported name when there is no model', () {
      expect(
        discoveredTitle(_device(manufacturer: '', model: '', name: 'Back door')),
        'Back door',
      );
    });

    test('uses whichever half is present', () {
      expect(discoveredTitle(_device(model: '')), 'Hikvision');
    });

    test('never renders an empty title', () {
      expect(
        discoveredTitle(_device(manufacturer: '', model: '', name: '')),
        'Camera',
      );
    });
  });

  group('discovered tile', () {
    testWidgets('shows address, resolution and whether a login is needed',
        (tester) async {
      await tester.pumpWidget(_wrap(
          DiscoveredTile(device: _device(), onUse: () {})));
      expect(find.text('Hikvision DS-2CD2043'), findsOneWidget);
      expect(find.text('192.168.1.64:80 · 1920x1080 · needs a login'),
          findsOneWidget);
    });

    testWidgets('a camera already added is shown, not hidden', (tester) async {
      // Hiding it would make "already added" indistinguishable from "not
      // found" for someone hunting a camera they just plugged in.
      await tester.pumpWidget(_wrap(
          DiscoveredTile(device: _device(alreadyAdded: true), onUse: () {})));
      expect(find.text('Added'), findsOneWidget);
    });

    testWidgets('an already-added camera cannot be picked', (tester) async {
      var used = 0;
      await tester.pumpWidget(_wrap(DiscoveredTile(
          device: _device(alreadyAdded: true), onUse: () => used++)));
      await tester.tap(find.byType(ListTile));
      await tester.pumpAndSettle();
      expect(used, 0);
    });

    testWidgets('a new camera can be picked', (tester) async {
      var used = 0;
      await tester.pumpWidget(_wrap(
          DiscoveredTile(device: _device(), onUse: () => used++)));
      await tester.tap(find.byType(ListTile));
      await tester.pumpAndSettle();
      expect(used, 1);
    });

    testWidgets('omits resolution when the camera did not report one',
        (tester) async {
      await tester.pumpWidget(_wrap(DiscoveredTile(
          device: _device(resolution: ''), onUse: () {})));
      expect(find.text('192.168.1.64:80 · needs a login'), findsOneWidget);
    });

    testWidgets('says nothing about a login when none is needed',
        (tester) async {
      await tester.pumpWidget(_wrap(DiscoveredTile(
          device: _device(authRequired: false), onUse: () {})));
      expect(find.text('192.168.1.64:80 · 1920x1080'), findsOneWidget);
    });
  });

  group('reorderList', () {
    test('moving an item down accounts for the removed slot', () {
      // ReorderableListView reports the target index in the pre-removal
      // list. Ignoring that puts the item one place short of where it
      // was dropped.
      expect(reorderList(const ['a', 'b', 'c'], 0, 3), ['b', 'c', 'a']);
    });

    test('moving an item up needs no adjustment', () {
      expect(reorderList(const ['a', 'b', 'c'], 2, 0), ['c', 'a', 'b']);
    });

    test('dropping an item where it already is changes nothing', () {
      expect(reorderList(const ['a', 'b', 'c'], 1, 1), ['a', 'b', 'c']);
    });
  });
}
