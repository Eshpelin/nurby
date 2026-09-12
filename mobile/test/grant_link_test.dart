import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:nurby_mobile/features/guardian/grant_link_sheet.dart';

Future<void> _pump(WidgetTester tester) async {
  await tester.pumpWidget(const ProviderScope(
    child: MaterialApp(home: Scaffold(body: GrantLinkSheet())),
  ));
  await tester.pump();
}

void main() {
  testWidgets('cannot advance past step one without an email', (tester) async {
    await _pump(tester);
    final next = tester.widget<FilledButton>(find.widgetWithText(FilledButton, 'Next'));
    expect(next.onPressed, isNull);

    await tester.enterText(find.widgetWithText(TextField, 'Their email'), 'not-an-email');
    await tester.pump();
    expect(tester.widget<FilledButton>(find.widgetWithText(FilledButton, 'Next')).onPressed, isNull);

    await tester.enterText(find.widgetWithText(TextField, 'Their email'), 'gran@example.com');
    await tester.pump();
    expect(tester.widget<FilledButton>(find.widgetWithText(FilledButton, 'Next')).onPressed, isNotNull);
  });

  testWidgets('says up front that the invitee sets their own password',
      (tester) async {
    // The admin never sees or relays a password when email works. That
    // is the safe path and the flow should say so on step one.
    await _pump(tester);
    expect(find.textContaining('set their own password'), findsOneWidget);
  });

  testWidgets('a valid email advances to choosing the person', (tester) async {
    await _pump(tester);
    await tester.enterText(find.widgetWithText(TextField, 'Their email'), 'a@b.c');
    await tester.pump();
    await tester.tap(find.widgetWithText(FilledButton, 'Next'));
    await tester.pump();
    expect(find.text('Which person may they watch?'), findsOneWidget);
    // And cannot advance again until one is picked.
    expect(tester.widget<FilledButton>(find.widgetWithText(FilledButton, 'Next')).onPressed, isNull);
  });
}
