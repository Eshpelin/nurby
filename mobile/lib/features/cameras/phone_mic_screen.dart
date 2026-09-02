import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:record/record.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../../core/providers.dart';
import '../../core/theme.dart';

/// Use this phone as a microphone for one camera (issue #172).
///
/// The web app has a page for exactly this, visited by a phone in a
/// browser. The native app captures raw PCM and streams it to
/// /ws/mic/{camera_id}, which pipes it through ffmpeg into the TCP port
/// the AudioWorker already listens on. The server is told the format in
/// the query string, because raw PCM has no header to probe.
///
/// The one rule of this screen: it must never be ambiguous whether the
/// microphone is live. It streams to a household system.
class PhoneMicScreen extends ConsumerStatefulWidget {
  const PhoneMicScreen({super.key, required this.cameraId, required this.cameraName});

  final String cameraId;
  final String cameraName;

  @override
  ConsumerState<PhoneMicScreen> createState() => _PhoneMicScreenState();
}

enum _MicState { idle, connecting, live, stopped, denied, error }

class _PhoneMicScreenState extends ConsumerState<PhoneMicScreen> {
  static const _rate = 16000;

  final _recorder = AudioRecorder();
  WebSocketChannel? _channel;
  StreamSubscription<Uint8List>? _audio;
  StreamSubscription<dynamic>? _server;
  _MicState _state = _MicState.idle;
  String? _detail;
  int _bytes = 0;
  DateTime? _since;
  Timer? _tick;

  @override
  void dispose() {
    _stop();
    _recorder.dispose();
    super.dispose();
  }

  Future<void> _start() async {
    if (!await _recorder.hasPermission()) {
      setState(() {
        _state = _MicState.denied;
        _detail = 'Nurby was not allowed to use the microphone. Turn it on '
            'in your phone\'s settings and try again.';
      });
      return;
    }
    setState(() {
      _state = _MicState.connecting;
      _detail = null;
    });

    final api = ref.read(apiClientProvider);
    final wsBase = ref.read(serverConfigProvider).wsBaseUrl;
    if (wsBase == null) {
      setState(() {
        _state = _MicState.error;
        _detail = 'No server configured.';
      });
      return;
    }
    final uri = Uri.parse('$wsBase/ws/mic/${widget.cameraId}').replace(
      queryParameters: {
        'token': api.token ?? '',
        'format': 'pcm',
        'rate': '$_rate',
        'channels': '1',
      },
    );

    try {
      final channel = WebSocketChannel.connect(uri);
      await channel.ready;
      _channel = channel;
      _server = channel.stream.listen(
        (msg) {
          // The server sends {"type":"ready"} once ffmpeg is up and
          // {"type":"error"} if it dies. Anything else is ignored.
          final text = msg is String ? msg : '';
          if (text.contains('"error"')) {
            _fail('The server could not take audio: $text');
          }
        },
        onError: (Object e) => _fail('Connection lost: $e'),
        onDone: () {
          if (_state == _MicState.live) _fail('The server closed the connection.');
        },
      );

      final stream = await _recorder.startStream(const RecordConfig(
        encoder: AudioEncoder.pcm16bits,
        sampleRate: _rate,
        numChannels: 1,
      ));
      _audio = stream.listen((chunk) {
        _channel?.sink.add(chunk);
        _bytes += chunk.length;
      });

      setState(() {
        _state = _MicState.live;
        _since = DateTime.now();
      });
      _tick = Timer.periodic(const Duration(seconds: 1), (_) {
        if (mounted) setState(() {});
      });
    } catch (e) {
      _fail('$e');
    }
  }

  void _fail(String why) {
    _stop(keepDetail: why);
  }

  Future<void> _stop({String? keepDetail}) async {
    _tick?.cancel();
    _tick = null;
    await _audio?.cancel();
    _audio = null;
    if (await _recorder.isRecording()) await _recorder.stop();
    await _server?.cancel();
    _server = null;
    await _channel?.sink.close();
    _channel = null;
    if (mounted) {
      setState(() {
        _state = keepDetail == null ? _MicState.stopped : _MicState.error;
        _detail = keepDetail;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final live = _state == _MicState.live;
    final elapsed = _since == null ? Duration.zero : DateTime.now().difference(_since!);

    return Scaffold(
      appBar: AppBar(title: Text('Mic for ${widget.cameraName}')),
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            // Big, red, and the only thing on screen while live. Not a
            // status dot in a corner.
            Container(
              width: 140,
              height: 140,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: live
                    ? NurbyColors.danger.withValues(alpha: 0.18)
                    : NurbyColors.cardElevated,
                border: Border.all(
                    color: live ? NurbyColors.danger : NurbyColors.border,
                    width: 3),
              ),
              child: Icon(
                live ? Icons.mic : Icons.mic_none,
                size: 56,
                color: live ? NurbyColors.danger : NurbyColors.mutedForeground,
              ),
            ),
            const SizedBox(height: 20),
            Text(
              switch (_state) {
                _MicState.idle => 'Not sending',
                _MicState.connecting => 'Connecting',
                _MicState.live => 'LIVE',
                _MicState.stopped => 'Stopped',
                _MicState.denied => 'Microphone blocked',
                _MicState.error => 'Stopped',
              },
              style: TextStyle(
                fontSize: 22,
                fontWeight: FontWeight.w700,
                letterSpacing: live ? 2 : 0,
                color: live ? NurbyColors.danger : null,
              ),
            ),
            if (live) ...[
              const SizedBox(height: 6),
              Text(
                '${_fmt(elapsed)} · ${(_bytes / 1024).toStringAsFixed(0)} KB sent',
                style: const TextStyle(
                    fontFamily: 'Menlo',
                    fontSize: 12,
                    color: NurbyColors.mutedForeground),
              ),
            ],
            if (_detail != null) ...[
              const SizedBox(height: 12),
              Text(_detail!,
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                      fontSize: 13, color: NurbyColors.mutedForeground)),
            ],
            const SizedBox(height: 28),
            FilledButton.icon(
              style: FilledButton.styleFrom(
                backgroundColor: live ? NurbyColors.danger : null,
                minimumSize: const Size(200, 48),
              ),
              onPressed: _state == _MicState.connecting
                  ? null
                  : (live ? () => _stop() : _start),
              icon: Icon(live ? Icons.stop : Icons.mic),
              label: Text(live ? 'Stop' : 'Start sending'),
            ),
            const SizedBox(height: 24),
            const Text(
              'Audio from this phone is treated as if it came from the '
              'camera: transcribed, and heard by any rule listening to it. '
              'It stops the moment you leave this screen.',
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 12, color: NurbyColors.mutedForeground),
            ),
          ],
        ),
      ),
    );
  }

  static String _fmt(Duration d) =>
      '${d.inMinutes.toString().padLeft(2, '0')}:'
      '${(d.inSeconds % 60).toString().padLeft(2, '0')}';
}
