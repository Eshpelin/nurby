import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:nurby_mobile/features/guardian/guardian_cards.dart';

/// Pumps the three cards with whatever each provider should resolve to.
/// Overrides are built here rather than passed in, because Riverpod's
/// `Override` type is not part of flutter_riverpod's public exports and
/// so cannot be named in a test signature.
Future<void> _pump(
  WidgetTester tester, {
  Object? wellbeing,
  Object? trends,
  Object? events,
}) async {
  Future<Map<String, dynamic>> resolve(Object? v, Map<String, dynamic> fallback) async {
    if (v is Exception) throw v;
    if (v is Map<String, dynamic>) return v;
    return fallback;
  }

  await tester.pumpWidget(ProviderScope(
    overrides: [
      wellbeingProvider('l1')
          .overrideWith((ref) => resolve(wellbeing, _wellbeing())),
      trendsProvider('l1').overrideWith((ref) => resolve(trends, _trends())),
      guardianEventsProvider('l1')
          .overrideWith((ref) => resolve(events, _events())),
    ],
    child: const MaterialApp(
      home: Scaffold(
        body: SingleChildScrollView(
          child: Column(children: [
            WellbeingCard(linkId: 'l1'),
            TrendsCard(linkId: 'l1'),
            GuardianEventsCard(linkId: 'l1'),
          ]),
        ),
      ),
    ),
  ));
  await tester.pumpAndSettle();
}

DioException _forbidden() => DioException(
      requestOptions: RequestOptions(path: '/x'),
      response: Response(
          requestOptions: RequestOptions(path: '/x'), statusCode: 403),
    );

void main() {
  group('isForbidden', () {
    test('recognises a 403 as a tier limit, not a failure', () {
      expect(isForbidden(_forbidden()), isTrue);
    });

    test('any other error is a real error', () {
      expect(isForbidden(Exception('boom')), isFalse);
      expect(
        isForbidden(DioException(
          requestOptions: RequestOptions(path: '/x'),
          response: Response(
              requestOptions: RequestOptions(path: '/x'), statusCode: 500),
        )),
        isFalse,
      );
    });
  });

  group('capability gating', () {
    testWidgets('a refused card names the limit instead of erroring',
        (tester) async {
      // A guardian on the alerts-only tier can do nothing about this. An
      // error message would read as something broken, which for someone
      // checking on a parent is the wrong thing to imply.
      await _pump(tester,
          wellbeing: _forbidden(), trends: _forbidden(), events: _forbidden());

      expect(find.textContaining('not part of this link'), findsNWidgets(3));
      expect(find.textContaining('403'), findsNothing);
    });

    testWidgets('a real error still surfaces', (tester) async {
      await _pump(tester, wellbeing: Exception('server down'));
      expect(find.textContaining('not part of this link'), findsNothing);
    });
  });

  group('wellbeing', () {
    testWidgets('says when they were seen eating', (tester) async {
      await _pump(tester, wellbeing: _wellbeing(ate: true));
      expect(find.text('Seen eating today'), findsOneWidget);
    });

    testWidgets('says when they were not, rather than staying silent',
        (tester) async {
      await _pump(tester, wellbeing: _wellbeing(ate: false));
      expect(find.text('Not seen eating today'), findsOneWidget);
    });

    testWidgets('always carries the best-effort caveat', (tester) async {
      // This card is read by someone worried about a parent. It must
      // never imply it is a medical record.
      await _pump(tester);
      expect(find.text(kBestEffortNote), findsOneWidget);
    });

    testWidgets('a fall is shown with when, not just that it happened',
        (tester) async {
      final at = DateTime.now()
          .toUtc()
          .subtract(const Duration(hours: 3))
          .toIso8601String();
      await _pump(tester, wellbeing: _wellbeing(lastFallAt: at));
      expect(find.textContaining('Possible fall detected'), findsOneWidget);
      expect(find.textContaining('3h ago'), findsOneWidget);
    });

    testWidgets('no fall means no fall row at all', (tester) async {
      await _pump(tester);
      expect(find.textContaining('Possible fall'), findsNothing);
    });

    testWidgets('a delayed view says so', (tester) async {
      // "Nothing happened" and "nothing has reached you yet" are very
      // different things to read about a parent.
      await _pump(tester, wellbeing: _wellbeing(delayed: true));
      expect(find.text('delayed view'), findsWidgets);
    });
  });

  group('trends', () {
    testWidgets('summarises days seen out of the window', (tester) async {
      await _pump(tester);
      expect(find.text('Seen on 5 of 7 days'), findsOneWidget);
    });
  });

  group('alerts', () {
    testWidgets('says plainly when nothing was raised', (tester) async {
      await _pump(tester, events: <String, dynamic>{'items': <dynamic>[]});
      expect(find.text('Nothing raised recently.'), findsOneWidget);
    });

    testWidgets('renders each alert message', (tester) async {
      await _pump(tester);
      expect(find.text('Left home'), findsOneWidget);
    });
  });
}

Map<String, dynamic> _wellbeing({
  bool ate = true,
  String? lastFallAt,
  bool delayed = false,
}) =>
    {
      'counts': {'eating': 3, 'sitting': 8},
      'ate_today': ate,
      'eating_events_today': ate ? 2 : 0,
      'last_fall_at': lastFallAt,
      'last_action': null,
      'window_days': 7,
      'delayed': delayed,
    };

Map<String, dynamic> _trends() => {
      'display_name': 'Mum',
      'window_days': 7,
      'days_seen': 5,
      'total_sightings': 40,
      'days': [
        for (var i = 0; i < 7; i++)
          {'date': '2026-09-0${i + 1}', 'sightings': i == 2 ? 0 : 6},
      ],
      'delayed': false,
    };

Map<String, dynamic> _events() => {
      'items': [
        {
          'id': 'e1',
          'kind': 'departed',
          'message': 'Left home',
          'severity': 'info',
          'at': DateTime.now().toUtc().toIso8601String(),
        },
      ],
    };
