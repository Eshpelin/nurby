import 'package:shared_preferences/shared_preferences.dart';

/// Persisted pointer to the user's self-hosted Nurby server.
class ServerConfig {
  ServerConfig(this._prefs);

  /// Public so the background isolate (core/push.dart) can rebuild an
  /// ApiClient from the same persisted value.
  static const baseUrlKey = 'server_base_url';
  final SharedPreferences _prefs;

  String? get baseUrl => _prefs.getString(baseUrlKey);

  Future<void> setBaseUrl(String url) async {
    var normalized = url.trim();
    if (normalized.endsWith('/')) {
      normalized = normalized.substring(0, normalized.length - 1);
    }
    if (!normalized.startsWith('http')) {
      normalized = 'http://$normalized';
    }
    await _prefs.setString(baseUrlKey, normalized);
  }

  Future<void> clear() => _prefs.remove(baseUrlKey);

  /// ws:// or wss:// equivalent of the base URL.
  String? get wsBaseUrl {
    final base = baseUrl;
    if (base == null) return null;
    return base.replaceFirst('http', 'ws');
  }
}
