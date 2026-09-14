import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'core/providers.dart';
import 'core/theme.dart';
import 'features/admin/admin_screens.dart';
import 'features/activity/activity_screen.dart';
import 'features/auth/login_screen.dart';
import 'features/auth/qr_pair_screen.dart';
import 'features/auth/server_screen.dart';
import 'features/auth/setup_screen.dart';
import 'features/ask/ask_screen.dart';
import 'features/cameras/camera_detail_screen.dart';
import 'features/cameras/cameras_screen.dart';
import 'features/guardian/guardian_admin_screen.dart';
import 'features/guardian/guardian_claim_screen.dart';
import 'features/guardian/guardian_notifications_screen.dart';
import 'features/guardian/guardian_screen.dart';
import 'features/guardian/guardian_shell.dart';
import 'features/home/home_screen.dart';
import 'features/notifications/notifications_screen.dart';
import 'features/people/people_screen.dart';
import 'features/follow/follow_screen.dart';
import 'features/reports/reports_screen.dart';
import 'features/rules/rule_editor_screen.dart';
import 'features/rules/rules_screen.dart';
import 'features/search/search_screen.dart';
import 'features/settings/settings_hub_screen.dart';
import 'features/settings/settings_screen.dart';
import 'features/shares/shares_screen.dart';
import 'features/shell/shell_screen.dart';
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
    initialLocation: '/home',
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
          // Guardian mode: a guardian-role user has exactly two places
          // and none of the household's. Keep them there. Everyone else
          // goes to Home; the household side of guardian lives under
          // Settings > Sharing.
          final isGuardian = ref.read(authProvider).user?.role == 'guardian';
          if (isGuardian) {
            return loc.startsWith('/guardian') ? null : '/guardian';
          }
          return onAuthPage ? '/home' : null;
      }
    },
    routes: [
      GoRoute(path: '/server', builder: (_, __) => const ServerScreen()),
      GoRoute(path: '/pair', builder: (_, __) => const QrPairScreen()),
      GoRoute(path: '/login', builder: (_, __) => const LoginScreen()),
      GoRoute(path: '/setup', builder: (_, __) => const SetupScreen()),
      GoRoute(
        path: '/guardian',
        builder: (_, state) => GuardianShell(
            initialTab: state.uri.queryParameters['tab'] == 'updates' ? 1 : 0),
      ),
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
          // The five places (docs/ia-rollout.md). Each is a question:
          // Home is everything all right, Cameras show me, Activity what
          // happened, Ask tell me, People who is that.
          StatefulShellBranch(routes: [
            GoRoute(path: '/home', builder: (_, __) => const HomeScreen()),
          ]),
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
            GoRoute(
              path: '/activity',
              builder: (_, state) => ActivityScreen(
                  initialKind:
                      ActivityKind.fromSlug(state.uri.queryParameters['kind'])),
            ),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(
              path: '/ask',
              builder: (_, __) => const AskScreen(),
              routes: [
                GoRoute(
                    path: 'scheduled', builder: (_, __) => const ReportsScreen()),
              ],
            ),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(
              path: '/people',
              builder: (_, __) => const PeopleScreen(),
              routes: [
                GoRoute(
                  path: 'follow/:kind/:id',
                  builder: (_, state) => FollowScreen(
                    kind: state.pathParameters['kind'] ?? 'person',
                    id: state.pathParameters['id']!,
                  ),
                ),
                GoRoute(
                    path: 'vehicles', builder: (_, __) => const VehiclesScreen()),
              ],
            ),
          ]),
        ],
      ),
      // Settings hub and everything that used to live under /more.
      GoRoute(
        path: '/settings',
        builder: (_, __) => const SettingsHubScreen(),
        routes: [
          GoRoute(path: 'general', builder: (_, __) => const SettingsScreen()),
          GoRoute(path: 'rules', builder: (_, __) => const RulesScreen()),
          GoRoute(path: 'rules/new', builder: (_, __) => const RuleEditorScreen()),
          GoRoute(
            path: 'rules/:id/edit',
            builder: (_, state) =>
                RuleEditorScreen(ruleId: state.pathParameters['id']),
          ),
          GoRoute(path: 'reports', builder: (_, __) => const ReportsScreen()),
          GoRoute(
              path: 'notifications',
              builder: (_, __) => const NotificationsScreen()),
          GoRoute(path: 'shares', builder: (_, __) => const SharesScreen()),
          GoRoute(
            path: 'guardian',
            builder: (_, __) => const GuardianScreen(),
            routes: [
              GoRoute(
                  path: 'notifications',
                  builder: (_, __) => const GuardianNotificationsScreen()),
              GoRoute(path: 'admin', builder: (_, __) => const GuardianAdminScreen()),
            ],
          ),
          GoRoute(path: 'access', builder: (_, __) => const CameraAccessScreen()),
          GoRoute(path: 'pipeline', builder: (_, __) => const PipelineScreen()),
          GoRoute(path: 'ask-admin', builder: (_, __) => const AskAdminScreen()),
        ],
      ),
      GoRoute(path: '/search', builder: (_, __) => const SearchScreen()),

      // Old routes keep resolving. Anything bookmarked, deep-linked from
      // a push, or hard-coded in a test lands where it now lives.
      GoRoute(path: '/timeline', redirect: (_, __) => '/activity'),
      GoRoute(path: '/alerts', redirect: (_, __) => '/activity?kind=alerts'),
      GoRoute(path: '/more', redirect: (_, __) => '/settings'),
      GoRoute(
        path: '/more/:rest(.*)',
        redirect: (_, state) => legacyMorePath(state.pathParameters['rest'] ?? ''),
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


/// Where each old /more/... path went. Activity kinds become filters;
/// the rest moved under /settings or /people unchanged.
String legacyMorePath(String rest) {
  const kinds = {
    'incidents': 'incidents',
    'journeys': 'journeys',
    'conversations': 'conversations',
    'digests': 'recaps',
    'recordings': 'recordings',
  };
  final head = rest.split('/').first;
  if (kinds.containsKey(head)) return '/activity?kind=${kinds[head]}';
  if (head == 'people') return '/people${rest.substring('people'.length)}';
  if (head == 'vehicles') return '/people/vehicles';
  if (head == 'search') return '/search';
  if (head == 'settings') return '/settings/general';
  return '/settings/$rest';
}
