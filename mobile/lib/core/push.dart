import 'dart:async';
import 'dart:developer';
import 'dart:io';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:workmanager/workmanager.dart';

import 'api_client.dart';
import 'server_config.dart';

/// Everything push: local notifications, optional FCM registration, and the
/// pull path (poll unread/unreviewed counts, notify when they grow). Nothing
/// here is load-bearing; every step logs and degrades silently, because a
/// stock Nurby server has no push config at all.

const _logName = 'push';

/// Keep in sync with pubspec.yaml `version:`; sent when registering a device.
const kAppVersion = '1.0.0+1';

/// SharedPreferences keys for the pull path baseline.
const kLastUnreadKey = 'push_last_unread';
const kLastUnreviewedKey = 'push_last_unreviewed';

/// SharedPreferences key: last FCM token registered with the server.
const kFcmTokenKey = 'push_fcm_token';

/// SharedPreferences key: one-time permission prompt shown after first login.
const kPermissionPromptedKey = 'push_permission_prompted';

/// Workmanager unique name; doubles as the iOS BGTaskScheduler identifier,
/// so it must appear in Info.plist BGTaskSchedulerPermittedIdentifiers and in
/// AppDelegate's WorkmanagerPlugin.registerPeriodicTask call.
const kBackgroundTaskId = 'com.nurby.nurbyMobile.alertcheck';

/// Thin wrapper over flutter_local_notifications.
class NotificationService {
  final FlutterLocalNotificationsPlugin _plugin =
      FlutterLocalNotificationsPlugin();
  bool _ready = false;

  static const _channel = AndroidNotificationChannel(
    'nurby_alerts',
    'Nurby alerts',
    description: 'Rule firings and camera notifications',
    importance: Importance.high,
  );

  Future<void> init() async {
    try {
      const android = AndroidInitializationSettings('@mipmap/ic_launcher');
      const ios = DarwinInitializationSettings(
        requestAlertPermission: true,
        requestBadgePermission: true,
        requestSoundPermission: true,
      );
      await _plugin.initialize(
          const InitializationSettings(android: android, iOS: ios));
      await _plugin
          .resolvePlatformSpecificImplementation<
              AndroidFlutterLocalNotificationsPlugin>()
          ?.createNotificationChannel(_channel);
      _ready = true;
    } catch (e) {
      log('notification init failed: $e', name: _logName);
    }
  }

  /// iOS system dialog / Android 13+ POST_NOTIFICATIONS runtime permission.
  Future<void> requestPermissions() async {
    try {
      await _plugin
          .resolvePlatformSpecificImplementation<
              AndroidFlutterLocalNotificationsPlugin>()
          ?.requestNotificationsPermission();
      await _plugin
          .resolvePlatformSpecificImplementation<
              IOSFlutterLocalNotificationsPlugin>()
          ?.requestPermissions(alert: true, badge: true, sound: true);
    } catch (e) {
      log('permission request failed: $e', name: _logName);
    }
  }

  Future<void> show(String title, String body, {String? payload}) async {
    if (!_ready) return;
    try {
      await _plugin.show(
        DateTime.now().millisecondsSinceEpoch.remainder(1 << 31),
        title,
        body,
        NotificationDetails(
          android: AndroidNotificationDetails(
            _channel.id,
            _channel.name,
            channelDescription: _channel.description,
            importance: Importance.high,
            priority: Priority.high,
          ),
          iOS: const DarwinNotificationDetails(),
        ),
        payload: payload,
      );
    } catch (e) {
      log('notification show failed: $e', name: _logName);
    }
  }
}

// ---- Pull path: count-diff alerts -----------------------------------------

class AlertCheckResult {
  const AlertCheckResult({
    required this.newAlerts,
    required this.unread,
    required this.unreviewed,
  });

  /// How many alerts arrived since the stored baseline (0 on first run).
  final int newAlerts;
  final int unread;
  final int unreviewed;
}

/// Pure diff logic: alerts that are new relative to the last-seen baseline.
/// A null baseline (first run) never counts as new; shrinking counts (acked
/// or read elsewhere) contribute nothing.
int countNewAlerts({
  required int unread,
  required int unreviewed,
  int? lastUnread,
  int? lastUnreviewed,
}) {
  var grown = 0;
  if (lastUnread != null && unread > lastUnread) {
    grown += unread - lastUnread;
  }
  if (lastUnreviewed != null && unreviewed > lastUnreviewed) {
    grown += unreviewed - lastUnreviewed;
  }
  return grown;
}

/// Applies fresh counts against the stored baseline: fires one local
/// notification when something grew, then persists the new baseline.
/// Split from [checkAlertsNow] so tests can inject fake counts.
Future<AlertCheckResult> applyAlertCounts({
  required SharedPreferences prefs,
  required NotificationService notifications,
  required int unread,
  required int unreviewed,
}) async {
  final newAlerts = countNewAlerts(
    unread: unread,
    unreviewed: unreviewed,
    lastUnread: prefs.getInt(kLastUnreadKey),
    lastUnreviewed: prefs.getInt(kLastUnreviewedKey),
  );
  if (newAlerts > 0) {
    await notifications.show(
        'Nurby', newAlerts == 1 ? '1 new alert' : '$newAlerts new alerts');
  }
  await prefs.setInt(kLastUnreadKey, unread);
  await prefs.setInt(kLastUnreviewedKey, unreviewed);
  return AlertCheckResult(
      newAlerts: newAlerts, unread: unread, unreviewed: unreviewed);
}

/// Polls the server for unread notification / unreviewed event counts and
/// notifies if they grew. Used by the background task, and by the "Check
/// alerts now" tile in More.
Future<AlertCheckResult> checkAlertsNow(
  ApiClient api,
  SharedPreferences prefs,
  NotificationService notifications,
) async {
  final notifJson = await api.getJson('/api/notifications/count') as Map;
  final eventsJson = await api.getJson('/api/events/count') as Map;
  return applyAlertCounts(
    prefs: prefs,
    notifications: notifications,
    unread: notifJson['unread'] as int? ?? 0,
    unreviewed: eventsJson['unreviewed_count'] as int? ?? 0,
  );
}

// ---- Background fetch (workmanager) ----------------------------------------

/// Runs in a background isolate: rebuild a bare API client from the same
/// persisted server url (SharedPreferences) + token (secure storage) the
/// foreground app uses, then run the count-diff check.
@pragma('vm:entry-point')
void callbackDispatcher() {
  Workmanager().executeTask((taskName, inputData) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final baseUrl = prefs.getString(ServerConfig.baseUrlKey);
      if (baseUrl == null) return true;
      final api = ApiClient(baseUrl: baseUrl);
      await api.loadToken(); // flutter_secure_storage 'auth_token'
      if (!api.hasToken) return true;
      final notifications = NotificationService();
      await notifications.init();
      await checkAlertsNow(api, prefs, notifications);
    } catch (e) {
      // Server unreachable, token expired, etc. Nothing to retry urgently;
      // the next periodic run will try again.
      log('background alert check failed: $e', name: _logName);
    }
    return true;
  });
}

// ---- FCM + lifecycle wiring -------------------------------------------------

/// Owns the login/logout side effects: FCM device registration (when the
/// server exposes a Firebase config) and the periodic background pull task.
class PushManager {
  PushManager(this._notifications);

  final NotificationService _notifications;
  StreamSubscription<String>? _tokenSub;
  StreamSubscription<RemoteMessage>? _messageSub;

  /// Called whenever auth transitions to loggedIn (startup or fresh login).
  Future<void> onLogin(ApiClient api, SharedPreferences prefs) async {
    await _tryRegisterFcm(api, prefs);
    await _tryRegisterBackgroundRefresh();
  }

  /// Called when auth leaves loggedIn. Device-row deletion happens earlier
  /// (while the token is still valid); this just stops local machinery.
  Future<void> onLogout() async {
    await _tokenSub?.cancel();
    _tokenSub = null;
    await _messageSub?.cancel();
    _messageSub = null;
    try {
      await Workmanager().cancelByUniqueName(kBackgroundTaskId);
    } catch (e) {
      log('workmanager cancel failed: $e', name: _logName);
    }
  }

  /// Best-effort server-side cleanup; call before the auth token is cleared.
  static Future<void> deleteDevice(
      ApiClient api, SharedPreferences prefs) async {
    final token = prefs.getString(kFcmTokenKey);
    if (token == null) return;
    try {
      await api.delete('/api/push/devices/$token');
      await prefs.remove(kFcmTokenKey);
    } catch (e) {
      log('push device delete failed: $e', name: _logName);
    }
  }

  Future<void> _tryRegisterFcm(ApiClient api, SharedPreferences prefs) async {
    try {
      final cfg = await api.getJson('/api/push/config');
      final fb = cfg is Map ? cfg['firebase_web_config'] : null;
      if (fb is! Map) {
        // Normal case today: server has no push config.
        log('no firebase config on server; FCM disabled', name: _logName);
        return;
      }
      try {
        await Firebase.initializeApp(
          options: FirebaseOptions(
            apiKey: fb['apiKey'] as String? ?? '',
            appId: fb['appId'] as String? ?? '',
            messagingSenderId: fb['messagingSenderId'] as String? ?? '',
            projectId: fb['projectId'] as String? ?? '',
            authDomain: fb['authDomain'] as String?,
            storageBucket: fb['storageBucket'] as String?,
          ),
        );
      } on FirebaseException catch (e) {
        // duplicate-app on re-login is fine; anything else disables FCM.
        if (e.code != 'duplicate-app') rethrow;
      }
      final messaging = FirebaseMessaging.instance;
      final token = await messaging.getToken();
      if (token == null) return;
      await _registerDevice(api, prefs, token);
      _tokenSub ??= messaging.onTokenRefresh.listen((t) {
        _registerDevice(api, prefs, t).catchError(
            (Object e) => log('token refresh re-register failed: $e',
                name: _logName));
      });
      _messageSub ??= FirebaseMessaging.onMessage.listen((msg) {
        final n = msg.notification;
        _notifications.show(
          n?.title ?? 'Nurby',
          n?.body ?? msg.data['message']?.toString() ?? 'New alert',
        );
      });
    } catch (e) {
      log('FCM registration skipped: $e', name: _logName);
    }
  }

  Future<void> _registerDevice(
      ApiClient api, SharedPreferences prefs, String token) async {
    await api.postJson('/api/push/devices', body: {
      'platform': Platform.isIOS ? 'ios' : 'android',
      'token': token,
      'app_version': kAppVersion,
    });
    await prefs.setString(kFcmTokenKey, token);
  }

  Future<void> _tryRegisterBackgroundRefresh() async {
    try {
      await Workmanager().initialize(callbackDispatcher);
      await Workmanager().registerPeriodicTask(
        kBackgroundTaskId,
        kBackgroundTaskId,
        frequency: const Duration(minutes: 15),
        existingWorkPolicy: ExistingWorkPolicy.keep,
        constraints: Constraints(networkType: NetworkType.connected),
      );
    } catch (e) {
      log('background refresh registration failed: $e', name: _logName);
    }
  }
}
