import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nurby_mobile/core/providers.dart';
import 'package:nurby_mobile/core/theme.dart';
import 'package:nurby_mobile/features/auth/login_screen.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  testWidgets('login screen renders fields and server url', (tester) async {
    SharedPreferences.setMockInitialValues(
        {'server_base_url': 'http://10.0.0.5:8000'});
    final prefs = await SharedPreferences.getInstance();

    await tester.pumpWidget(ProviderScope(
      overrides: [sharedPrefsProvider.overrideWithValue(prefs)],
      child: MaterialApp(theme: buildNurbyTheme(), home: const LoginScreen()),
    ));

    expect(find.text('Sign in'), findsWidgets);
    expect(find.text('http://10.0.0.5:8000'), findsOneWidget);
    expect(find.widgetWithText(TextField, 'Email'), findsOneWidget);
    expect(find.widgetWithText(TextField, 'Password'), findsOneWidget);
    expect(find.text('Change server'), findsOneWidget);
  });

  testWidgets('server screen shown fields', (tester) async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();

    await tester.pumpWidget(ProviderScope(
      overrides: [sharedPrefsProvider.overrideWithValue(prefs)],
      child: MaterialApp(theme: buildNurbyTheme(), home: const LoginScreen()),
    ));

    // Without a server URL the login screen still renders (router guards
    // normally prevent this state); just assert no crash.
    expect(find.byType(TextField), findsNWidgets(2));
  });
}
