import 'package:shared_preferences/shared_preferences.dart';

/// Persisted pointer to the user's self-hosted Nurby server.
class ServerConfig {
  ServerConfig(this._prefs);

  static const _kBaseUrl = 'server_base_url';
  final SharedPreferences _prefs;

  String? get baseUrl => _prefs.getString(_kBaseUrl);

  Future<void> setBaseUrl(String url) async {
    var normalized = url.trim();
    if (normalized.endsWith('/')) {
      normalized = normalized.substring(0, normalized.length - 1);
    }
    if (!normalized.startsWith('http')) {
      normalized = 'http://$normalized';
    }
    await _prefs.setString(_kBaseUrl, normalized);
  }

  Future<void> clear() => _prefs.remove(_kBaseUrl);

  /// ws:// or wss:// equivalent of the base URL.
  String? get wsBaseUrl {
    final base = baseUrl;
    if (base == null) return null;
    return base.replaceFirst('http', 'ws');
  }
}
