import 'dart:async';
import 'dart:convert';

import 'package:web_socket_channel/web_socket_channel.dart';

/// Live dashboard websocket (/ws?token=). Broadcasts decoded JSON messages;
/// reconnects with capped exponential backoff (1..30s) like the web client.
class NurbyWsClient {
  NurbyWsClient({required this.wsBaseUrl, required this.token});

  final String wsBaseUrl;
  final String token;

  final _messages = StreamController<Map<String, dynamic>>.broadcast();
  final _status = StreamController<WsStatus>.broadcast();

  Stream<Map<String, dynamic>> get messages => _messages.stream;
  Stream<WsStatus> get status => _status.stream;
  WsStatus lastStatus = WsStatus.connecting;

  WebSocketChannel? _channel;
  StreamSubscription<dynamic>? _sub;
  Timer? _reconnectTimer;
  int _attempt = 0;
  bool _closed = false;

  void connect() {
    if (_closed) return;
    _setStatus(_attempt == 0 ? WsStatus.connecting : WsStatus.reconnecting);
    try {
      final uri = Uri.parse('$wsBaseUrl/ws?token=$token');
      _channel = WebSocketChannel.connect(uri);
      _sub = _channel!.stream.listen(
        (data) {
          _attempt = 0;
          _setStatus(WsStatus.connected);
          try {
            final decoded = jsonDecode(data as String);
            if (decoded is Map<String, dynamic>) _messages.add(decoded);
          } catch (_) {
            // Non-JSON frame; ignore.
          }
        },
        onDone: _scheduleReconnect,
        onError: (_) => _scheduleReconnect(),
        cancelOnError: true,
      );
    } catch (_) {
      _scheduleReconnect();
    }
  }

  void _scheduleReconnect() {
    if (_closed) return;
    _setStatus(WsStatus.reconnecting);
    _sub?.cancel();
    _channel = null;
    final delay = Duration(seconds: [1, 2, 4, 8, 16, 30][_attempt.clamp(0, 5)]);
    _attempt++;
    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(delay, connect);
  }

  void _setStatus(WsStatus s) {
    lastStatus = s;
    if (!_status.isClosed) _status.add(s);
  }

  void dispose() {
    _closed = true;
    _reconnectTimer?.cancel();
    _sub?.cancel();
    _channel?.sink.close();
    _messages.close();
    _status.close();
  }
}

enum WsStatus { connecting, connected, reconnecting, disconnected }
