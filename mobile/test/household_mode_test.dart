import 'package:flutter_test/flutter_test.dart';
import 'package:nurby_mobile/models/household_mode.dart';

void main() {
  group('ruleActiveIn', () {
    test('a rule with no modes fires in every mode', () {
      for (final m in kHouseholdModes) {
        expect(ruleActiveIn(null, m), isTrue);
        expect(ruleActiveIn({}, m), isTrue);
        expect(ruleActiveIn({'modes': <String>[]}, m), isTrue);
        expect(ruleActiveIn({'camera_id': 'x'}, m), isTrue);
      }
    });

    test('a gated rule fires only in the modes it names', () {
      final cond = {
        'modes': ['away', 'night']
      };
      expect(ruleActiveIn(cond, 'away'), isTrue);
      expect(ruleActiveIn(cond, 'night'), isTrue);
      expect(ruleActiveIn(cond, 'home'), isFalse);
    });

    test('a malformed modes value does not gate the rule', () {
      // Failing open here matters: a rule the client cannot parse must
      // keep firing, not go silently quiet.
      expect(ruleActiveIn({'modes': 'away'}, 'home'), isTrue);
    });
  });

  group('labels', () {
    test('an ungated rule has no gate label', () {
      expect(modeGateLabel(null), isNull);
      expect(modeGateLabel({'modes': <String>[]}), isNull);
      expect(modePausedLabel(null), isNull);
    });

    test('one mode', () {
      expect(modeGateLabel({'modes': ['away']}), 'Only while Away');
      expect(modePausedLabel({'modes': ['away']}), 'Paused until Away');
    });

    test('two modes read the way a person would say it', () {
      expect(modeGateLabel({'modes': ['away', 'night']}),
          'Only while Away or Night');
      expect(modePausedLabel({'modes': ['away', 'night']}),
          'Paused until Away or Night');
    });

    test('an unknown mode is dropped rather than shown raw', () {
      expect(modeGateLabel({'modes': ['away', 'vacation']}), 'Only while Away');
      expect(modeGateLabel({'modes': ['vacation']}), isNull);
    });

    test('every mode has a label', () {
      for (final m in kHouseholdModes) {
        expect(kModeLabels[m], isNotNull);
      }
    });
  });

  group('HouseholdModeState', () {
    final json = {
      'mode': 'away',
      'since': '2026-09-15T11:32:00.621051Z',
      'source': 'manual',
      'modes': [
        {'key': 'home', 'label': 'Home', 'hint': 'Someone is in.'},
        {'key': 'away', 'label': 'Away', 'hint': 'Nobody home.'},
        {'key': 'night', 'label': 'Night', 'hint': 'In for the night.'},
      ],
      'history': [
        {
          'id': 'abc',
          'mode': 'away',
          'previous_mode': 'home',
          'source': 'manual',
          'changed_by_name': 'Sam',
          'note': 'off to work',
          'changed_at': '2026-09-15T11:32:00.621051Z',
        }
      ],
      'silenced_rule_count': 2,
    };

    test('parses the server payload', () {
      final s = HouseholdModeState.fromJson(json);
      expect(s.mode, 'away');
      expect(s.silencedRuleCount, 2);
      expect(s.modes.map((m) => m.key), ['home', 'away', 'night']);
      expect(s.active?.label, 'Away');
      expect(s.history.single.changedByName, 'Sam');
      expect(s.history.single.note, 'off to work');
      expect(s.history.single.previousMode, 'home');
    });

    test('labels come from the server, not the local constants', () {
      // The point of serving them: a fourth mode added to the backend
      // renders without a client release.
      final s = HouseholdModeState.fromJson({
        ...json,
        'mode': 'holiday',
        'modes': [
          {'key': 'holiday', 'label': 'Holiday', 'hint': 'Away for a while.'}
        ],
      });
      expect(s.active?.label, 'Holiday');
      expect(s.active?.hint, 'Away for a while.');
    });

    test('survives a payload missing every optional field', () {
      final s = HouseholdModeState.fromJson({'mode': 'home'});
      expect(s.mode, 'home');
      expect(s.since, isNull);
      expect(s.modes, isEmpty);
      expect(s.history, isEmpty);
      expect(s.silencedRuleCount, 0);
    });

    test('defaults to home when the server sends nothing', () {
      expect(HouseholdModeState.fromJson({}).mode, 'home');
    });
  });
}
