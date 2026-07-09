import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nurby_mobile/core/api_client.dart';

DioException _err(
  DioExceptionType type, {
  String method = 'GET',
  Object? error,
  int? status,
}) {
  final options = RequestOptions(path: '/api/things', method: method);
  return DioException(
    requestOptions: options,
    type: type,
    error: error,
    response: status == null
        ? null
        : Response(requestOptions: options, statusCode: status),
  );
}

void main() {
  group('shouldRetry decision table', () {
    test('retries GET connection errors up to the delay-table length', () {
      final e = _err(DioExceptionType.connectionError);
      expect(shouldRetry(e, 0), isTrue);
      expect(shouldRetry(e, 1), isTrue);
      expect(shouldRetry(e, 2), isFalse); // max 2 retries
      expect(shouldRetry(e, 99), isFalse);
    });

    test('retries GET connect/receive timeouts', () {
      expect(shouldRetry(_err(DioExceptionType.connectionTimeout), 0), isTrue);
      expect(shouldRetry(_err(DioExceptionType.receiveTimeout), 0), isTrue);
    });

    test('retries GET unknown errors only when caused by SocketException', () {
      expect(
        shouldRetry(
          _err(DioExceptionType.unknown,
              error: const SocketException('connection reset')),
          0,
        ),
        isTrue,
      );
      expect(
        shouldRetry(
            _err(DioExceptionType.unknown, error: StateError('boom')), 0),
        isFalse,
      );
      expect(shouldRetry(_err(DioExceptionType.unknown), 0), isFalse);
    });

    test('never retries non-GET methods', () {
      for (final method in ['POST', 'PATCH', 'PUT', 'DELETE']) {
        expect(
          shouldRetry(
              _err(DioExceptionType.connectionError, method: method), 0),
          isFalse,
          reason: '$method must not be retried',
        );
      }
    });

    test('never retries response errors, even 5xx on GET', () {
      expect(
        shouldRetry(_err(DioExceptionType.badResponse, status: 500), 0),
        isFalse,
      );
      expect(
        shouldRetry(_err(DioExceptionType.badResponse, status: 404), 0),
        isFalse,
      );
    });

    test('never retries cancellations or bad certificates', () {
      expect(shouldRetry(_err(DioExceptionType.cancel), 0), isFalse);
      expect(shouldRetry(_err(DioExceptionType.badCertificate), 0), isFalse);
    });

    test('sendTimeout is not in the retryable set', () {
      expect(shouldRetry(_err(DioExceptionType.sendTimeout), 0), isFalse);
    });
  });

  group('retryDelays', () {
    test('is 400ms then 1200ms', () {
      expect(retryDelays, const [
        Duration(milliseconds: 400),
        Duration(milliseconds: 1200),
      ]);
    });
  });
}
