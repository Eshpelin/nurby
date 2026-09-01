import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'core/providers.dart';
import 'core/theme.dart';
import 'features/admin/admin_screens.dart';
import 'features/auth/login_screen.dart';
import 'features/auth/qr_pair_screen.dart';
import 'features/auth/server_screen.dart';
import 'features/auth/setup_screen.dart';
import 'features/ask/ask_screen.dart';
import 'features/cameras/camera_detail_screen.dart';
import 'features/cameras/cameras_screen.dart';
import 'features/events/events_screen.dart';
import 'features/guardian/guardian_admin_screen.dart';
import 'features/guardian/guardian_claim_screen.dart';
import 'features/guardian/guardian_notifications_screen.dart';
import 'features/guardian/guardian_screen.dart';
import 'features/more/more_screen.dart';
import 'features/notifications/notifications_screen.dart';
import 'features/people/people_screen.dart';
import 'features/conversations/conversations_screen.dart';
import 'features/digests/digests_screen.dart';
import 'features/follow/follow_screen.dart';
import 'features/incidents/incidents_screen.dart';
import 'features/journeys/journeys_screen.dart';
import 'features/recordings/recordings_screen.dart';
import 'features/reports/reports_screen.dart';
import 'features/rules/rule_editor_screen.dart';
import 'features/rules/rules_screen.dart';
import 'features/search/search_screen.dart';
import 'features/settings/settings_screen.dart';
import 'features/shares/shares_screen.dart';
import 'features/shell/shell_screen.dart';
import 'features/timeline/timeline_screen.dart';
import 'features/vehicles/vehicles_screen.dart';

class NurbyApp extends ConsumerWidget {
  const NurbyApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Keep the WS -> local-notification bridge alive for the app's lifetime.
    ref.watch(wsNotificationBridgeProvider);
    // Replay offline-queued mutations on reconnect / app resume.
    ref.watch(outboxDrainProvider);

    // FCM + background-refresh registration follows the auth phase.
    ref.listen(authProvider, (prev, next) {
      final wasIn = prev?.phase == AuthPhase.loggedIn;
      final isIn = next.phase == AuthPhase.loggedIn;
      if (!wasIn && isIn) {
        unawaited(ref.read(pushManagerProvider).onLogin(
            ref.read(apiClientProvider), ref.read(sharedPrefsProvider)));
      } else if (wasIn && !isIn) {
        unawaited(ref.read(pushManagerProvider).onLogout());
      }
    });

    final router = ref.watch(_routerProvider);
    return MaterialApp.router(
      title: 'Nurby',
      debugShowCheckedModeBanner: false,
      theme: buildNurbyTheme(),
      routerConfig: router,
    );
  }
}

final _routerProvider = Provider<GoRouter>((ref) {
  final notifier = _AuthChangeNotifier(ref);
  ref.onDispose(notifier.dispose);

  return GoRouter(
    initialLocation: '/cameras',
    refreshListenable: notifier,
    redirect: (context, state) {
      final phase = ref.read(authProvider).phase;
      final loc = state.matchedLocation;
      final onAuthPage = loc == '/server' ||
          loc == '/login' ||
          loc == '/setup' ||
          loc == '/checking' ||
          loc == '/pair';
      // Accepting a guardian invite happens before an account exists:
      // the magic-link token in the invite is the credential. Redirecting
      // it to /login would make the invite impossible to accept.
      final isClaim = loc.startsWith('/guardian/claim');
      switch (phase) {
        case AuthPhase.noServer:
          return (loc == '/server' || loc == '/pair') ? null : '/server';
        case AuthPhase.checking:
          return loc == '/checking' ? null : '/checking';
        case AuthPhase.needsSetup:
          return loc == '/setup' ? null : '/setup';
        case AuthPhase.loggedOut:
          return (loc == '/login' ||
                  loc == '/server' ||
                  loc == '/pair' ||
                  isClaim)
              ? null
              : '/login';
        case AuthPhase.loggedIn:
          return onAuthPage ? '/cameras' : null;
      }
    },
    routes: [
      GoRoute(path: '/server', builder: (_, __) => const ServerScreen()),
      GoRoute(path: '/pair', builder: (_, __) => const QrPairScreen()),
      GoRoute(path: '/login', builder: (_, __) => const LoginScreen()),
      GoRoute(path: '/setup', builder: (_, __) => const SetupScreen()),
      GoRoute(
        path: '/guardian/claim',
        builder: (_, state) => GuardianClaimScreen(
            token: state.uri.queryParameters['token']),
      ),
      GoRoute(
        path: '/checking',
        builder: (_, __) => const Scaffold(
          body: Center(child: CircularProgressIndicator()),
        ),
      ),
      StatefulShellRoute.indexedStack(
        builder: (context, state, shell) => ShellScreen(shell: shell),
        branches: [
          StatefulShellBranch(routes: [
            GoRoute(
              path: '/cameras',
              builder: (_, __) => const CamerasScreen(),
              routes: [
                GoRoute(
                  path: ':id',
                  builder: (_, state) =>
                      CameraDetailScreen(cameraId: state.pathParameters['id']!),
                ),
              ],
            ),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(path: '/timeline', builder: (_, __) => const TimelineScreen()),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(path: '/ask', builder: (_, __) => const AskScreen()),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(path: '/alerts', builder: (_, __) => const EventsScreen()),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(
              path: '/more',
              builder: (_, __) => const MoreScreen(),
              routes: [
                GoRoute(path: 'rules', builder: (_, __) => const RulesScreen()),
                GoRoute(
                  path: 'rules/new',
                  builder: (_, __) => const RuleEditorScreen(),
                ),
                GoRoute(
                  path: 'rules/:id/edit',
                  builder: (_, state) =>
                      RuleEditorScreen(ruleId: state.pathParameters['id']),
                ),
                GoRoute(
                  path: 'people',
                  builder: (_, __) => const PeopleScreen(),
                  routes: [
                    // kind is person or cluster: the two follow endpoints
                    // are keyed differently but return the same bundle.
                    GoRoute(
                      path: 'follow/:kind/:id',
                      builder: (_, state) => FollowScreen(
                        kind: state.pathParameters['kind'] ?? 'person',
                        id: state.pathParameters['id']!,
                      ),
                    ),
                  ],
                ),
                GoRoute(
                    path: 'vehicles', builder: (_, __) => const VehiclesScreen()),
                GoRoute(
                    path: 'incidents',
                    builder: (_, __) => const IncidentsScreen()),
                GoRoute(
                    path: 'journeys', builder: (_, __) => const JourneysScreen()),
                GoRoute(
                    path: 'conversations',
                    builder: (_, __) => const ConversationsScreen()),
                GoRoute(
                    path: 'digests', builder: (_, __) => const DigestsScreen()),
                GoRoute(
                    path: 'reports', builder: (_, __) => const ReportsScreen()),
                GoRoute(
                    path: 'access', builder: (_, __) => const CameraAccessScreen()),
                GoRoute(
                    path: 'pipeline', builder: (_, __) => const PipelineScreen()),
                GoRoute(
                    path: 'ask-admin', builder: (_, __) => const AskAdminScreen()),
                GoRoute(
                    path: 'recordings',
                    builder: (_, __) => const RecordingsScreen()),
                GoRoute(path: 'search', builder: (_, __) => const SearchScreen()),
                GoRoute(path: 'shares', builder: (_, __) => const SharesScreen()),
                GoRoute(
                    path: 'notifications',
                    builder: (_, __) => const NotificationsScreen()),
                GoRoute(
                  path: 'guardian',
                  builder: (_, __) => const GuardianScreen(),
                  routes: [
                    GoRoute(
                      path: 'notifications',
                      builder: (_, __) => const GuardianNotificationsScreen(),
                    ),
                    GoRoute(
                      path: 'admin',
                      builder: (_, __) => const GuardianAdminScreen(),
                    ),
                  ],
                ),
                GoRoute(
                    path: 'settings', builder: (_, __) => const SettingsScreen()),
              ],
            ),
          ]),
        ],
      ),
    ],
  );
});

class _AuthChangeNotifier extends ChangeNotifier {
  _AuthChangeNotifier(Ref ref) {
    _sub = ref.listen(authProvider, (_, __) => notifyListeners());
  }
  late final ProviderSubscription _sub;

  @override
  void dispose() {
    _sub.close();
    super.dispose();
  }
}
