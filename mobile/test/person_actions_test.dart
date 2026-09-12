import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:nurby_mobile/features/people/person_actions.dart';
import 'package:nurby_mobile/models/models.dart';

Person _p(String id, String name) =>
    Person.fromJson({'id': id, 'display_name': name});

void main() {
  testWidgets('merge confirmation names both sides and which one survives',
      (tester) async {
    // Merge is the one irreversible person operation. A generic "are you
    // sure" here would be worse than no dialog.
    final target = _p('t', 'Sam');
    final source = _p('s', 'Sam (duplicate)');
    late BuildContext ctx;
    await tester.pumpWidget(ProviderScope(
      child: MaterialApp(
        home: Consumer(builder: (c, ref, _) {
          ctx = c;
          return TextButton(
            onPressed: () => confirmMerge(c, ref, target, source),
            child: const Text('go'),
          );
        }),
      ),
    ));
    await tester.tap(find.text('go'));
    await tester.pumpAndSettle();

    expect(find.textContaining('will no longer exist as a separate person'),
        findsOneWidget);
    expect(find.textContaining('This cannot be undone'), findsOneWidget);
    // The confirm button says which one survives, not just "Merge".
    expect(find.text('Merge into Sam'), findsOneWidget);
    expect(ctx, isNotNull);
  });

  testWidgets('merge picker excludes nobody but explains what to pick',
      (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: MergePickerSheet(
          source: _p('s', 'Dup'),
          others: [_p('a', 'Alex'), _p('b', 'Bo')],
        ),
      ),
    ));
    expect(find.text('Merge Dup into'), findsOneWidget);
    expect(find.text('Alex'), findsOneWidget);
    expect(find.text('Bo'), findsOneWidget);
    expect(find.textContaining('the one that should survive'), findsOneWidget);
  });
}
