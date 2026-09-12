import 'package:flutter_test/flutter_test.dart';
import 'package:nurby_mobile/features/ask/ask_extras.dart';

const _sam = Mention(kind: 'person', id: 'p1', name: 'Sam');
const _samantha = Mention(kind: 'person', id: 'p2', name: 'Samantha');
const _front = Mention(kind: 'camera', id: 'c1', name: 'Front door');

void main() {
  group('activeMentionQuery', () {
    test('an @ at the start opens the picker', () {
      expect(activeMentionQuery('@sa', 3), 'sa');
    });

    test('an @ after a space opens the picker', () {
      expect(activeMentionQuery('did @sa', 7), 'sa');
    });

    test('an @ inside a word is not a mention', () {
      // An email address must not open the picker.
      expect(activeMentionQuery('mail me@x', 9), isNull);
    });

    test('a completed mention followed by a space closes the picker', () {
      expect(activeMentionQuery('@Sam go', 7), isNull);
    });

    test('only text before the cursor counts', () {
      expect(activeMentionQuery('@sa later', 3), 'sa');
    });

    test('a bare @ opens the picker with an empty query', () {
      expect(activeMentionQuery('@', 1), '');
    });

    test('no @ means no picker', () {
      expect(activeMentionQuery('hello', 5), isNull);
    });
  });

  group('insertMention', () {
    test('replaces the partial token and leaves a trailing space', () {
      final r = insertMention('did @sa', 7, 'Sam');
      expect(r.text, 'did @Sam ');
      expect(r.cursor, 9);
    });

    test('keeps text after the cursor', () {
      final r = insertMention('@sa go out', 3, 'Sam');
      expect(r.text, '@Sam  go out');
      expect(r.cursor, 5);
    });
  });

  group('mentionsStillPresent', () {
    test('drops a mention whose name was deleted from the text', () {
      // Picking a person and then deleting them must not tell the API
      // about someone the question no longer names.
      expect(mentionsStillPresent('what did @Sam do', [_sam, _front]), [_sam]);
    });

    test('keeps every mention still named', () {
      expect(
        mentionsStillPresent('@Sam at @Front door', [_sam, _front]),
        [_sam, _front],
      );
    });
  });

  group('matchMentions', () {
    test('prefix matches rank above substring matches', () {
      final r = matchMentions([_front, _samantha, _sam], 'sa');
      expect(r.map((m) => m.name).toList(), ['Samantha', 'Sam']);
    });

    test('is case-insensitive', () {
      expect(matchMentions([_sam], 'SAM').single, _sam);
    });

    test('an empty query offers everything', () {
      expect(matchMentions([_sam, _front], '').length, 2);
    });

    test('respects the cap', () {
      final many = [for (var i = 0; i < 20; i++) Mention(kind: 'person', id: '$i', name: 'P$i')];
      expect(matchMentions(many, 'p').length, 6);
    });
  });

  group('Mention.toRef', () {
    test('sends exactly what MentionRef expects', () {
      expect(_sam.toRef(), {'kind': 'person', 'id': 'p1', 'name': 'Sam'});
    });
  });

  group('usageSummary', () {
    test('reports tokens and cost when both budgets exist', () {
      expect(
        usageSummary({
          'used_tokens': 12500,
          'token_budget': 100000,
          'used_cost_cents': 42,
          'cost_budget_cents': 500,
        }),
        '12.5k of 100k tokens, \$0.42 of \$5.00',
      );
    });

    test('says so when no budget is set', () {
      expect(usageSummary({'used_tokens': 5}), 'No budget set');
    });

    test('a zero budget is treated as unset, not as fully used', () {
      expect(usageSummary({'used_tokens': 5, 'token_budget': 0}),
          'No budget set');
    });
  });
}
