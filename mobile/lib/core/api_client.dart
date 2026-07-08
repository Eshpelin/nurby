import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Thin wrapper over Dio: attaches JWT, exposes typed helpers,
/// signals auth expiry so the app can route back to login.
class ApiClient {
  ApiClient({required String baseUrl, void Function()? onUnauthorized})
      : _onUnauthorized = onUnauthorized,
        dio = Dio(BaseOptions(
          baseUrl: baseUrl,
          connectTimeout: const Duration(seconds: 10),
          receiveTimeout: const Duration(seconds: 30),
        )) {
    dio.interceptors.add(InterceptorsWrapper(
      onRequest: (options, handler) {
        final token = _token;
        if (token != null) {
          options.headers['Authorization'] = 'Bearer $token';
        }
        handler.next(options);
      },
      onError: (e, handler) {
        if (e.response?.statusCode == 401) {
          _onUnauthorized?.call();
        }
        handler.next(e);
      },
    ));
  }

  static const _storage = FlutterSecureStorage();
  static const _kToken = 'auth_token';

  final Dio dio;
  final void Function()? _onUnauthorized;
  String? _token;

  String? get token => _token;
  String get baseUrl => dio.options.baseUrl;

  Future<void> loadToken() async {
    _token = await _storage.read(key: _kToken);
  }

  Future<void> setToken(String token) async {
    _token = token;
    await _storage.write(key: _kToken, value: token);
  }

  Future<void> clearToken() async {
    _token = null;
    await _storage.delete(key: _kToken);
  }

  bool get hasToken => _token != null;

  /// Media endpoints (video/img tags server-side) accept ?token= because
  /// native players cannot send Authorization headers.
  String mediaUrl(String path, [Map<String, String>? params]) {
    final uri = Uri.parse('$baseUrl$path').replace(queryParameters: {
      if (_token != null) 'token': _token!,
      ...?params,
    });
    return uri.toString();
  }

  Future<dynamic> getJson(String path, {Map<String, dynamic>? query}) async {
    final res = await dio.get<dynamic>(path, queryParameters: query);
    return res.data;
  }

  Future<dynamic> postJson(String path, {Object? body}) async {
    final res = await dio.post<dynamic>(path, data: body);
    return res.data;
  }

  Future<dynamic> patchJson(String path, {Object? body}) async {
    final res = await dio.patch<dynamic>(path, data: body);
    return res.data;
  }

  Future<void> delete(String path) => dio.delete<void>(path);
}

/// Human-readable message out of a Dio error.
String apiErrorMessage(Object error) {
  if (error is DioException) {
    final data = error.response?.data;
    if (data is Map && data['detail'] is String) return data['detail'] as String;
    if (data is Map && data['detail'] is List) {
      final items = data['detail'] as List;
      if (items.isNotEmpty && items.first is Map) {
        return (items.first as Map)['msg']?.toString() ?? 'Validation error';
      }
    }
    switch (error.type) {
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.connectionError:
        return 'Cannot reach server. Check the address and your network.';
      case DioExceptionType.receiveTimeout:
        return 'Server took too long to respond.';
      default:
        break;
    }
    final code = error.response?.statusCode;
    if (code != null) return 'Request failed ($code)';
  }
  return 'Something went wrong';
}
