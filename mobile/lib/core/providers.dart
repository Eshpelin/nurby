import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api_client.dart';
import 'repositories.dart';
import 'server_config.dart';
import 'ws_client.dart';
import '../models/models.dart';

/// Overridden in main() after SharedPreferences loads.
final sharedPrefsProvider =
    Provider<SharedPreferences>((ref) => throw UnimplementedError());

final serverConfigProvider =
    Provider<ServerConfig>((ref) => ServerConfig(ref.watch(sharedPrefsProvider)));

/// App-level auth phase driving the router.
enum AuthPhase { noServer, checking, loggedOut, needsSetup, loggedIn }

class AppAuthState {
  const AppAuthState(this.phase, {this.user});
  final AuthPhase phase;
  final User? user;

  AppAuthState copyWith({AuthPhase? phase, User? user}) =>
      AppAuthState(phase ?? this.phase, user: user ?? this.user);
}

class AuthController extends Notifier<AppAuthState> {
  ApiClient? _api;

  @override
  AppAuthState build() {
    final config = ref.watch(serverConfigProvider);
    if (config.baseUrl == null) return const AppAuthState(AuthPhase.noServer);
    _initApi(config.baseUrl!);
    Future.microtask(_bootstrap);
    return const AppAuthState(AuthPhase.checking);
  }

  void _initApi(String baseUrl) {
    _api = ApiClient(baseUrl: baseUrl, onUnauthorized: _handleUnauthorized);
  }

  ApiClient get api => _api!;

  Future<void> _bootstrap() async {
    try {
      await api.loadToken();
      if (api.hasToken) {
        final user = await AuthRepository(api).me();
        state = AppAuthState(AuthPhase.loggedIn, user: user);
        return;
      }
      final needsSetup = await AuthRepository(api).needsSetup();
      state = AppAuthState(
          needsSetup ? AuthPhase.needsSetup : AuthPhase.loggedOut);
    } catch (_) {
      // Token invalid or server unreachable; fall back to login.
      await api.clearToken();
      state = const AppAuthState(AuthPhase.loggedOut);
    }
  }

  Future<void> setServer(String url) async {
    await ref.read(serverConfigProvider).setBaseUrl(url);
    ref.invalidateSelf();
  }

  Future<void> login(String email, String password) async {
    final (token, user) = await AuthRepository(api).login(email, password);
    await api.setToken(token);
    state = AppAuthState(AuthPhase.loggedIn, user: user);
  }

  Future<void> setup(String email, String displayName, String password) async {
    final (token, user) =
        await AuthRepository(api).setup(email, displayName, password);
    await api.setToken(token);
    state = AppAuthState(AuthPhase.loggedIn, user: user);
  }

  Future<void> register(
      String email, String displayName, String password, String invite) async {
    final (token, user) =
        await AuthRepository(api).register(email, displayName, password, invite);
    await api.setToken(token);
    state = AppAuthState(AuthPhase.loggedIn, user: user);
  }

  Future<void> logout() async {
    await api.clearToken();
    state = const AppAuthState(AuthPhase.loggedOut);
  }

  Future<void> changeServer() async {
    await api.clearToken();
    await ref.read(serverConfigProvider).clear();
    ref.invalidateSelf();
  }

  void _handleUnauthorized() {
    if (state.phase == AuthPhase.loggedIn) {
      api.clearToken();
      state = const AppAuthState(AuthPhase.loggedOut);
    }
  }
}

final authProvider = NotifierProvider<AuthController, AppAuthState>(
    AuthController.new);

final apiClientProvider = Provider<ApiClient>((ref) {
  ref.watch(authProvider); // rebuild when auth/server changes
  return ref.read(authProvider.notifier).api;
});

// ---- Repositories ----
final cameraRepoProvider =
    Provider((ref) => CameraRepository(ref.watch(apiClientProvider)));
final observationRepoProvider =
    Provider((ref) => ObservationRepository(ref.watch(apiClientProvider)));
final timelineRepoProvider =
    Provider((ref) => TimelineRepository(ref.watch(apiClientProvider)));
final eventRepoProvider =
    Provider((ref) => EventRepository(ref.watch(apiClientProvider)));
final ruleRepoProvider =
    Provider((ref) => RuleRepository(ref.watch(apiClientProvider)));
final personRepoProvider =
    Provider((ref) => PersonRepository(ref.watch(apiClientProvider)));
final searchRepoProvider =
    Provider((ref) => SearchRepository(ref.watch(apiClientProvider)));
final recordingRepoProvider =
    Provider((ref) => RecordingRepository(ref.watch(apiClientProvider)));
final notificationRepoProvider =
    Provider((ref) => NotificationRepository(ref.watch(apiClientProvider)));
final systemRepoProvider =
    Provider((ref) => SystemRepository(ref.watch(apiClientProvider)));

// ---- Live websocket ----
final wsClientProvider = Provider<NurbyWsClient?>((ref) {
  final auth = ref.watch(authProvider);
  if (auth.phase != AuthPhase.loggedIn) return null;
  final api = ref.watch(apiClientProvider);
  final wsBase = ref.watch(serverConfigProvider).wsBaseUrl;
  if (wsBase == null || api.token == null) return null;
  final client = NurbyWsClient(wsBaseUrl: wsBase, token: api.token!);
  client.connect();
  ref.onDispose(client.dispose);
  return client;
});

/// Broadcast stream of decoded WS messages; empty stream when logged out.
final wsMessagesProvider = StreamProvider<Map<String, dynamic>>((ref) {
  final client = ref.watch(wsClientProvider);
  return client?.messages ?? const Stream.empty();
});

final wsStatusProvider = StreamProvider<WsStatus>((ref) {
  final client = ref.watch(wsClientProvider);
  return client?.status ?? const Stream.empty();
});

// ---- Shared data providers ----
final camerasProvider = FutureProvider<List<Camera>>((ref) async {
  final repo = ref.watch(cameraRepoProvider);
  // Refresh every 10s like the web dashboard.
  final timer = Timer.periodic(const Duration(seconds: 10),
      (_) => ref.invalidateSelf());
  ref.onDispose(timer.cancel);
  return repo.list();
});

final unreviewedCountProvider = FutureProvider<int>((ref) async {
  ref.watch(wsMessagesProvider.select((m) {
    final type = m.value?['type'];
    return type == 'event' || type == 'event_fired' || type == 'notification';
  }));
  return ref.watch(eventRepoProvider).unreviewedCount();
});

final unreadNotificationsProvider = FutureProvider<int>((ref) async {
  ref.watch(wsMessagesProvider.select(
      (m) => m.value?['type'] == 'notification'));
  return ref.watch(notificationRepoProvider).unreadCount();
});
