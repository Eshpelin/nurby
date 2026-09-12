import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:nurby_mobile/features/guardian/guardian_admin_screen.dart';
import 'package:nurby_mobile/features/guardian/guardian_claim_screen.dart';

Map<String, dynamic> _link({
  String tier = 'full',
  String? revokedAt,
  bool liveVideo = false,
  String label = 'Grandma',
}) =>
    {
      'id': 'l1',
      'person_id': 'p1',
      'relationship_label': label,
      'tier': tier,
      'live_video': liveVideo,
      'audio': false,
      'revoked_at': revokedAt,
      'granted_at': '2026-09-01T10:00:00Z',
    };

Future<void> _pumpAdmin(
  WidgetTester tester, {
  List<Map<String, dynamic>> links = const [],
  List<Map<String, dynamic>> log = const [],
  List<Map<String, dynamic>> facilities = const [],
}) async {
  await tester.pumpWidget(ProviderScope(
    overrides: [
      grantedLinksProvider.overrideWith((ref) async => links),
      accessLogProvider.overrideWith((ref) async => log),
      facilitiesProvider.overrideWith((ref) async => facilities),
    ],
    child: const MaterialApp(home: GuardianAdminScreen()),
  ));
  await tester.pumpAndSettle();
}

void main() {
  group('granted links', () {
    testWidgets('a revoked link stays visible under its own heading',
        (tester) async {
      // "Nobody can watch us" and "we revoked someone last week" are
      // different facts. Filtering revoked links out would erase the
      // second one.
      await _pumpAdmin(tester, links: [
        _link(label: 'Grandma'),
        _link(label: 'Old carer', revokedAt: '2026-09-05T10:00:00Z'),
      ]);
      expect(find.text('Grandma'), findsOneWidget);
      expect(find.text('Revoked'), findsOneWidget);
      expect(find.text('Old carer'), findsOneWidget);
    });

    testWidgets('a revoked link offers no revoke button', (tester) async {
      await _pumpAdmin(tester,
          links: [_link(revokedAt: '2026-09-05T10:00:00Z')]);
      expect(find.byIcon(Icons.link_off), findsNothing);
    });

    testWidgets('tier is shown in words, not as a raw enum', (tester) async {
      await _pumpAdmin(tester, links: [_link(tier: 'alerts_only')]);
      expect(find.textContaining('Alerts only'), findsOneWidget);
      expect(find.textContaining('alerts_only'), findsNothing);
    });

    testWidgets('revoking explains what it does not undo', (tester) async {
      await _pumpAdmin(tester, links: [_link()]);
      await tester.tap(find.byIcon(Icons.link_off));
      await tester.pumpAndSettle();
      expect(find.textContaining('does not undo what they have already been shown'),
          findsOneWidget);
    });

    testWidgets('says plainly when nobody has access', (tester) async {
      await _pumpAdmin(tester);
      expect(find.text('Nobody has been granted access'), findsOneWidget);
    });
  });

  group('claim screen', () {
    testWidgets('prefills the token from the invite link', (tester) async {
      await tester.pumpWidget(const ProviderScope(
        child: MaterialApp(home: GuardianClaimScreen(token: 'abc123')),
      ));
      await tester.pumpAndSettle();
      expect(find.text('abc123'), findsOneWidget);
    });

    testWidgets('refuses a short password with a reason, before sending',
        (tester) async {
      // The server requires 8+. Catching it here means a reason on screen
      // rather than a 400 after the form already looked submitted.
      await tester.pumpWidget(const ProviderScope(
        child: MaterialApp(home: GuardianClaimScreen(token: 'abc123')),
      ));
      await tester.pumpAndSettle();
      await tester.enterText(
          find.widgetWithText(TextField, 'Choose a password'), 'short');
      await tester.tap(find.widgetWithText(FilledButton, 'Accept invite'));
      await tester.pumpAndSettle();
      expect(find.text('Use at least 8 characters.'), findsOneWidget);
    });

    testWidgets('refuses a mismatched confirmation', (tester) async {
      await tester.pumpWidget(const ProviderScope(
        child: MaterialApp(home: GuardianClaimScreen(token: 'abc123')),
      ));
      await tester.pumpAndSettle();
      await tester.enterText(
          find.widgetWithText(TextField, 'Choose a password'), 'longenough1');
      await tester.enterText(
          find.widgetWithText(TextField, 'Type it again'), 'longenough2');
      await tester.tap(find.widgetWithText(FilledButton, 'Accept invite'));
      await tester.pumpAndSettle();
      expect(find.text('The two do not match.'), findsOneWidget);
    });

    testWidgets('refuses an empty invite code', (tester) async {
      await tester.pumpWidget(const ProviderScope(
        child: MaterialApp(home: GuardianClaimScreen()),
      ));
      await tester.pumpAndSettle();
      await tester.enterText(
          find.widgetWithText(TextField, 'Choose a password'), 'longenough1');
      await tester.enterText(
          find.widgetWithText(TextField, 'Type it again'), 'longenough1');
      await tester.tap(find.widgetWithText(FilledButton, 'Accept invite'));
      await tester.pumpAndSettle();
      expect(find.text('Paste the code from your invite.'), findsOneWidget);
    });
  });
}
