import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:nurby_mobile/app.dart';
import 'package:nurby_mobile/core/providers.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// End-to-end flow against a real local backend.
/// Requires the Nurby API on http://localhost:4748 with user
/// owner@example.com / nurby-mobile-test1 (see docs/mobile-plan.md).
void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  final binding = IntegrationTestWidgetsFlutterBinding.instance;

  testWidgets('server -> login -> tabs walk-through', (tester) async {
    Future<void> shot(String name) async {
      try {
        await binding.takeScreenshot(name);
      } catch (_) {
        // Screenshots only work under `flutter drive`; ignore in plain runs.
      }
    }
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    // Keychain persists across reinstalls; a token from a previous run
    // would skip the login screen and break the flow below.
    await const FlutterSecureStorage().deleteAll();

    await tester.pumpWidget(ProviderScope(
      overrides: [sharedPrefsProvider.overrideWithValue(prefs)],
      child: const NurbyApp(),
    ));
    await tester.pumpAndSettle();

    // Server screen
    expect(find.text('Server address'), findsOneWidget);
    await tester.enterText(find.byType(TextField), 'http://localhost:4748');
    await tester.tap(find.text('Connect'));

    // Login screen (poll: server check runs async)
    var onLogin = false;
    for (var i = 0; i < 30; i++) {
      await tester.pump(const Duration(milliseconds: 500));
      if (find.text('Sign in').evaluate().isNotEmpty) {
        onLogin = true;
        break;
      }
    }
    expect(onLogin, isTrue, reason: 'Login screen did not appear');
    await tester.enterText(
        find.widgetWithText(TextField, 'Email'), 'owner@example.com');
    await tester.enterText(
        find.widgetWithText(TextField, 'Password'), 'nurby-mobile-test1');
    await tester.tap(find.widgetWithText(FilledButton, 'Sign in'));

    // Wait for auth + first camera load (poll instead of pumpAndSettle:
    // live tiles animate forever).
    var loggedIn = false;
    for (var i = 0; i < 40; i++) {
      await tester.pump(const Duration(milliseconds: 500));
      if (find.text('Cameras').evaluate().isNotEmpty) {
        loggedIn = true;
        break;
      }
    }
    expect(loggedIn, isTrue, reason: 'Cameras tab did not appear after login');
    await shot('01_cameras');

    Future<void> goTab(String label, String expectText) async {
      await tester.tap(find.descendant(
        of: find.byType(NavigationBar),
        matching: find.text(label),
      ));
      for (var i = 0; i < 20; i++) {
        await tester.pump(const Duration(milliseconds: 500));
        if (find.text(expectText).evaluate().isNotEmpty) return;
      }
      fail('$label tab: "$expectText" not found');
    }

    await goTab('Timeline', 'Timeline');
    await shot('02_timeline');
    await goTab('Alerts', 'Alerts');
    await shot('03_alerts');
    await goTab('Ask', 'Ask Nurby');
    await shot('04_ask');
    await goTab('More', 'Settings');
    await shot('05_more');

    // Open Rules from More
    await tester.tap(find.text('Rules'));
    for (var i = 0; i < 20; i++) {
      await tester.pump(const Duration(milliseconds: 500));
      if (find.text('Rules').evaluate().isNotEmpty) break;
    }
    expect(find.text('Rules'), findsWidgets);
  });
}
