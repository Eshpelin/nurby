import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:nurby_mobile/features/voice/voice_settings_card.dart';

/// Settings shaped the way GET /api/voice/settings returns them. Note the
/// asymmetry the card has to handle: the allowlist reads back prefixed
/// (`voice_may_confirm`) and is written unprefixed (`may_confirm`).
Map<String, dynamic> _settings({
  bool enabled = true,
  List<String> mayConfirm = const [],
  List<String> neverSay = const [],
}) =>
    {
      'voice_enabled': enabled,
      'voice_conversation_enabled': true,
      'voice_max_volume': 70,
      'voice_session_max_turns': 6,
      'voice_session_max_seconds': 120,
      'voice_quiet_hours_start': null,
      'voice_quiet_hours_end': null,
      'voice_may_confirm': mayConfirm,
      'voice_never_say': neverSay,
      'disclosure_keys': [
        {
          'key': 'names',
          'label': 'Greet people by name',
          'description': 'A stranger within earshot learns who lives here.',
        },
        {
          'key': 'schedule',
          'label': 'Mention when someone will be back',
          'description': 'It tells a visitor when the house is unoccupied.',
        },
      ],
      'always_forbidden': [
        'Saying whether anyone is or is not home',
        'Discussing doors, locks, codes or keys',
        'Claiming to be a person',
      ],
    };

void main() {
  group('disclosurePatch', () {
    test('writes the unprefixed key name the API accepts', () {
      // The API returns voice_may_confirm and accepts may_confirm.
      // Writing the read name stores something the API ignores, which
      // shows as an enabled permission the disclosure filter never sees.
      final patch = disclosurePatch(const [], 'names', allow: true);
      expect(patch.keys.single, 'may_confirm');
    });

    test('allowing a key appends it to what is already allowed', () {
      final patch =
          disclosurePatch(const ['names'], 'schedule', allow: true);
      expect(patch['may_confirm'], ['names', 'schedule']);
    });

    test('disallowing removes only that key', () {
      final patch =
          disclosurePatch(const ['names', 'schedule'], 'names', allow: false);
      expect(patch['may_confirm'], ['schedule']);
    });

    test('allowing a key that is already allowed does not duplicate it', () {
      // A duplicate would read back as one entry but count as two, so
      // "1 of 2 allowed" would start lying.
      final patch = disclosurePatch(const ['names'], 'names', allow: true);
      expect(patch['may_confirm'], ['names']);
    });

    test('disallowing a key that was never allowed is a no-op', () {
      final patch =
          disclosurePatch(const ['names'], 'schedule', allow: false);
      expect(patch['may_confirm'], ['names']);
    });

    test('never emits the absolute rules as a writable key', () {
      // Nothing in this card may offer to change those three. They are
      // structural in services/voice/disclosure.py.
      final patch = disclosurePatch(const [], 'names', allow: true);
      expect(patch.containsKey('always_forbidden'), isFalse);
      expect(patch.containsKey('voice_may_confirm'), isFalse);
    });
  });

  group('VoiceSettingsCard rendering', () {
    testWidgets('states the absolute rules verbatim', (tester) async {
      await _pump(tester, _settings());

      expect(find.text('Never allowed, whatever you choose'), findsOneWidget);
      expect(find.text('Saying whether anyone is or is not home'),
          findsOneWidget);
      expect(find.text('Claiming to be a person'), findsOneWidget);
    });

    testWidgets('summarises how many disclosures are on', (tester) async {
      await _pump(tester, _settings(mayConfirm: const ['names']));
      expect(find.text('1 of 2 disclosures allowed'), findsOneWidget);
    });

    testWidgets('says plainly when voice is off', (tester) async {
      await _pump(tester, _settings(enabled: false));
      expect(find.text('Off. Cameras will not speak.'), findsOneWidget);
    });

    testWidgets('disclosure checkboxes are unchecked by default',
        (tester) async {
      await _pump(tester, _settings());
      final boxes = tester
          .widgetList<CheckboxListTile>(find.byType(CheckboxListTile))
          .toList();
      expect(boxes, hasLength(2));
      expect(boxes.every((b) => b.value == false), isTrue);
    });

    testWidgets('an existing never-say phrase renders as a chip',
        (tester) async {
      await _pump(tester, _settings(neverSay: const ['the dog']));
      expect(find.widgetWithText(Chip, 'the dog'), findsOneWidget);
      expect(find.text('Nothing yet.'), findsNothing);
    });

    testWidgets('disclosure controls are inert while voice is off',
        (tester) async {
      await _pump(tester, _settings(enabled: false));
      final boxes =
          tester.widgetList<CheckboxListTile>(find.byType(CheckboxListTile));
      expect(boxes.every((b) => b.onChanged == null), isTrue);
    });
  });
}

Future<void> _pump(WidgetTester tester, Map<String, dynamic> settings) async {
  await tester.pumpWidget(ProviderScope(
    overrides: [
      voiceSettingsProvider.overrideWith((ref) async => settings),
    ],
    child: MaterialApp(
      home: Scaffold(
        body: ListView(children: const [VoiceSettingsCard()]),
      ),
    ),
  ));
  await tester.pumpAndSettle();
}
