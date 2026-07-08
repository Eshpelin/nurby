import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'core/providers.dart';
import 'core/theme.dart';
import 'features/auth/login_screen.dart';
import 'features/auth/server_screen.dart';
import 'features/auth/setup_screen.dart';
import 'features/ask/ask_screen.dart';
import 'features/cameras/camera_detail_screen.dart';
import 'features/cameras/cameras_screen.dart';
import 'features/events/events_screen.dart';
import 'features/guardian/guardian_screen.dart';
import 'features/more/more_screen.dart';
import 'features/notifications/notifications_screen.dart';
import 'features/people/people_screen.dart';
import 'features/recordings/recordings_screen.dart';
import 'features/rules/rule_editor_screen.dart';
import 'features/rules/rules_screen.dart';
import 'features/search/search_screen.dart';
import 'features/settings/settings_screen.dart';
import 'features/shell/shell_screen.dart';
import 'features/timeline/timeline_screen.dart';
import 'features/vehicles/vehicles_screen.dart';

class NurbyApp extends ConsumerWidget {
  const NurbyApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    // Keep the WS -> local-notification bridge alive for the app's lifetime.
    ref.watch(wsNotificationBridgeProvider);

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
      final onAuthPage =
          loc == '/server' || loc == '/login' || loc == '/setup' || loc == '/checking';
      switch (phase) {
        case AuthPhase.noServer:
          return loc == '/server' ? null : '/server';
        case AuthPhase.checking:
          return loc == '/checking' ? null : '/checking';
        case AuthPhase.needsSetup:
          return loc == '/setup' ? null : '/setup';
        case AuthPhase.loggedOut:
          return (loc == '/login' || loc == '/server') ? null : '/login';
        case AuthPhase.loggedIn:
          return onAuthPage ? '/cameras' : null;
      }
    },
    routes: [
      GoRoute(path: '/server', builder: (_, __) => const ServerScreen()),
      GoRoute(path: '/login', builder: (_, __) => const LoginScreen()),
      GoRoute(path: '/setup', builder: (_, __) => const SetupScreen()),
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
                GoRoute(path: 'people', builder: (_, __) => const PeopleScreen()),
                GoRoute(
                    path: 'vehicles', builder: (_, __) => const VehiclesScreen()),
                GoRoute(
                    path: 'recordings',
                    builder: (_, __) => const RecordingsScreen()),
                GoRoute(path: 'search', builder: (_, __) => const SearchScreen()),
                GoRoute(
                    path: 'notifications',
                    builder: (_, __) => const NotificationsScreen()),
                GoRoute(
                    path: 'guardian', builder: (_, __) => const GuardianScreen()),
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
