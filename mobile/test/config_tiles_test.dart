import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nurby_mobile/features/cameras/config_tiles.dart';

Widget _wrap(Widget child) =>
    MaterialApp(home: Scaffold(body: ListView(children: [child])));

void main() {
  _tiles160();
  group('ConfigSwitch', () {
    testWidgets('a disabled switch shows its value but cannot be flipped',
        (tester) async {
      var flipped = false;
      await tester.pumpWidget(_wrap(ConfigSwitch(
        title: 'Capture audio',
        subtitle: 'Required before any transcription.',
        value: true,
        enabled: false,
        onChanged: (_) => flipped = true,
      )));

      // The current state stays readable. That is the point of disabling
      // rather than hiding: someone without permission still needs to know
      // whether their camera is listening.
      expect(find.text('Capture audio'), findsOneWidget);
      expect(find.text('Required before any transcription.'), findsOneWidget);
      expect(tester.widget<Switch>(find.byType(Switch)).value, isTrue);

      await tester.tap(find.byType(Switch));
      await tester.pump();
      expect(flipped, isFalse);
    });
  });

  group('ConfigChoice', () {
    testWidgets('renders the label for the current value, not the raw value',
        (tester) async {
      await tester.pumpWidget(_wrap(ConfigChoice<String>(
        title: 'Transcript storage',
        value: 'summary_only',
        options: const ['full', 'summary_only', 'off'],
        labels: const {
          'full': 'Full text',
          'summary_only': 'Summary only',
          'off': 'Off (live only)',
        },
        onChanged: (_) {},
      )));

      expect(find.text('Summary only'), findsOneWidget);
      expect(find.text('summary_only'), findsNothing);
    });

    testWidgets('picking a different option reports the raw value',
        (tester) async {
      String? picked;
      await tester.pumpWidget(_wrap(ConfigChoice<String>(
        title: 'Digest period',
        value: '24h',
        options: const ['1h', '24h', '7d'],
        labels: const {'1h': 'Every hour', '24h': 'Daily', '7d': 'Weekly'},
        onChanged: (v) => picked = v,
      )));

      await tester.tap(find.text('Daily'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Weekly'));
      await tester.pumpAndSettle();

      expect(picked, '7d');
    });

    testWidgets('re-picking the current option does not fire a write',
        (tester) async {
      var calls = 0;
      await tester.pumpWidget(_wrap(ConfigChoice<String>(
        title: 'Digest period',
        value: '24h',
        options: const ['1h', '24h'],
        labels: const {'1h': 'Every hour', '24h': 'Daily'},
        onChanged: (_) => calls++,
      )));

      await tester.tap(find.text('Daily'));
      await tester.pumpAndSettle();
      // Tapping the option that is already set. A PATCH here would be a
      // pointless write, and on the audio endpoint it would also be a
      // pointless audit-log row.
      await tester.tap(find.text('Daily').last);
      await tester.pumpAndSettle();

      expect(calls, 0);
    });
  });

  group('ConfigNumber', () {
    testWidgets('rejects a value outside the server bounds', (tester) async {
      int? saved;
      await tester.pumpWidget(_wrap(ConfigNumber(
        title: 'Gap between conversations',
        value: 30,
        min: 5,
        max: 600,
        suffix: 'seconds',
        onChanged: (v) => saved = v,
      )));

      await tester.tap(find.text('Gap between conversations'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), '900');
      await tester.tap(find.text('Save'));
      await tester.pumpAndSettle();

      // The dialog stays open with an explanation rather than firing a
      // PATCH the server would 422.
      expect(saved, isNull);
      expect(find.text('Must be between 5 and 600'), findsOneWidget);
    });

    testWidgets('rejects text that is not a number', (tester) async {
      int? saved;
      await tester.pumpWidget(_wrap(ConfigNumber(
        title: 'Decoding quality',
        value: 1,
        min: 1,
        max: 10,
        onChanged: (v) => saved = v,
      )));

      await tester.tap(find.text('Decoding quality'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), 'high');
      await tester.tap(find.text('Save'));
      await tester.pumpAndSettle();

      expect(saved, isNull);
      expect(find.text('Enter a whole number'), findsOneWidget);
    });

    testWidgets('accepts a value on the boundary', (tester) async {
      int? saved;
      await tester.pumpWidget(_wrap(ConfigNumber(
        title: 'Audio retention',
        value: 7,
        min: 0,
        max: 3650,
        suffix: 'days',
        onChanged: (v) => saved = v,
      )));

      await tester.tap(find.text('Audio retention'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), '0');
      await tester.tap(find.text('Save'));
      await tester.pumpAndSettle();

      expect(saved, 0);
    });

    testWidgets('shows the suffix and hint together in the row', (tester) async {
      await tester.pumpWidget(_wrap(ConfigNumber(
        title: 'Close an incident after',
        value: 600,
        min: 30,
        max: 86400,
        suffix: 'seconds',
        hint: 'idle time before the subject counts as gone',
        onChanged: (_) {},
      )));

      expect(
        find.text('600 seconds · idle time before the subject counts as gone'),
        findsOneWidget,
      );
    });
  });

  group('ConfigText', () {
    testWidgets('a cleared value is reported as null, not an empty string',
        (tester) async {
      Object? saved = 'unset';
      await tester.pumpWidget(_wrap(ConfigText(
        title: 'Digest prompt',
        value: 'Watch the driveway',
        onChanged: (v) => saved = v,
      )));

      await tester.tap(find.text('Digest prompt'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), '   ');
      await tester.tap(find.text('Save'));
      await tester.pumpAndSettle();

      // Null falls back to the household default. An empty string would
      // pin the camera to a blank prompt, which is a different thing.
      expect(saved, isNull);
    });

    testWidgets('shows the placeholder when there is no value',
        (tester) async {
      await tester.pumpWidget(_wrap(ConfigText(
        title: 'Digest prompt',
        value: null,
        onChanged: (_) {},
      )));

      expect(find.text('default'), findsOneWidget);
    });

    testWidgets('cancelling does not report a change', (tester) async {
      var calls = 0;
      await tester.pumpWidget(_wrap(ConfigText(
        title: 'Digest prompt',
        value: 'Watch the driveway',
        onChanged: (_) => calls++,
      )));

      await tester.tap(find.text('Digest prompt'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), 'something else');
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();

      expect(calls, 0);
    });
  });
}

// --- Tiles added for #160 ---------------------------------------------

void _tiles160() {
  group('ConfigStringList', () {
    testWidgets('an empty list shows what empty means, not "none"',
        (tester) async {
      // An empty detect_classes means every class the model knows. A tile
      // reading "none" would say the opposite of the truth.
      await tester.pumpWidget(_wrap(ConfigStringList(
        title: 'Classes to detect',
        values: const [],
        placeholder: 'all classes',
        onChanged: (_) {},
      )));
      expect(find.textContaining('all classes'), findsOneWidget);
    });

    testWidgets('adding a value returns the whole list', (tester) async {
      List<String>? saved;
      await tester.pumpWidget(_wrap(ConfigStringList(
        title: 'Classes to detect',
        values: const ['person'],
        onChanged: (v) => saved = v,
      )));

      await tester.tap(find.text('Classes to detect'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), 'car');
      await tester.tap(find.text('Add'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Save'));
      await tester.pumpAndSettle();

      expect(saved, ['person', 'car']);
    });

    testWidgets('a duplicate is not added twice', (tester) async {
      List<String>? saved;
      await tester.pumpWidget(_wrap(ConfigStringList(
        title: 'Classes',
        values: const ['person'],
        onChanged: (v) => saved = v,
      )));

      await tester.tap(find.text('Classes'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), 'person');
      await tester.tap(find.text('Add'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Save'));
      await tester.pumpAndSettle();

      expect(saved, ['person']);
    });

    testWidgets('cancelling discards edits', (tester) async {
      var calls = 0;
      await tester.pumpWidget(_wrap(ConfigStringList(
        title: 'Classes',
        values: const ['person'],
        onChanged: (_) => calls++,
      )));

      await tester.tap(find.text('Classes'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), 'car');
      await tester.tap(find.text('Add'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();

      expect(calls, 0);
    });

    testWidgets('clearing every value still saves an empty list',
        (tester) async {
      // Emptying the list is a real edit, not a no-op. Treating it as
      // "nothing changed" would make the field impossible to reset.
      List<String>? saved;
      await tester.pumpWidget(_wrap(ConfigStringList(
        title: 'Classes',
        values: const ['person'],
        onChanged: (v) => saved = v,
      )));

      await tester.tap(find.text('Classes'));
      await tester.pumpAndSettle();
      await tester.tap(find.byIcon(Icons.cancel));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Save'));
      await tester.pumpAndSettle();

      expect(saved, isNotNull);
      expect(saved, isEmpty);
    });
  });

  group('ConfigProvider', () {
    const providers = [
      {'id': 'p1', 'name': 'Local Ollama', 'kind': 'ollama'},
      {'id': 'p2', 'name': 'Claude', 'kind': 'anthropic'},
    ];

    testWidgets('null reads as the household default, not as empty',
        (tester) async {
      await tester.pumpWidget(_wrap(const ConfigProvider(
        title: 'Model',
        value: null,
        providers: providers,
        onChanged: _noop,
      )));
      expect(find.text('Household default'), findsOneWidget);
    });

    testWidgets('a known id shows the provider name', (tester) async {
      await tester.pumpWidget(_wrap(const ConfigProvider(
        title: 'Model',
        value: 'p2',
        providers: providers,
        onChanged: _noop,
      )));
      expect(find.text('Claude'), findsOneWidget);
    });

    testWidgets('an id not in the list says so rather than showing a uuid',
        (tester) async {
      await tester.pumpWidget(_wrap(const ConfigProvider(
        title: 'Model',
        value: '9f3ab120-4c5d-4e6f-8a9b-000000000001',
        providers: providers,
        onChanged: _noop,
      )));
      expect(find.text('Unknown AI model'), findsOneWidget);
      expect(find.textContaining('9f3ab120'), findsNothing);
    });

    testWidgets('choosing the default reports null, and it is reachable',
        (tester) async {
      // Null is a real choice, not the absence of one. If dismissing and
      // choosing "household default" were indistinguishable, a camera
      // could never be handed back to the default once set.
      Object? saved = 'unset';
      await tester.pumpWidget(_wrap(ConfigProvider(
        title: 'Model',
        value: 'p1',
        providers: providers,
        onChanged: (v) => saved = v,
      )));

      await tester.tap(find.text('Local Ollama'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Household default'));
      await tester.pumpAndSettle();

      expect(saved, isNull);
    });

    testWidgets('dismissing the sheet changes nothing', (tester) async {
      var calls = 0;
      await tester.pumpWidget(_wrap(ConfigProvider(
        title: 'Model',
        value: 'p1',
        providers: providers,
        onChanged: (_) => calls++,
      )));

      await tester.tap(find.text('Local Ollama'));
      await tester.pumpAndSettle();
      await tester.tapAt(const Offset(200, 50)); // scrim
      await tester.pumpAndSettle();

      expect(calls, 0);
    });
  });
}

void _noop(String? _) {}
