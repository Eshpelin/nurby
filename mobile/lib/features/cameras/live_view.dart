import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:video_player/video_player.dart';

import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../models/models.dart';
import 'detection_overlay.dart';
import 'whep_player.dart';

/// Picks the right renderer for a camera stream, mirroring the web dashboard:
/// rtsp/usb -> WebRTC WHEP via MediaMTX (HLS fallback),
/// file/http(s) -> direct video, snapshot/webcam -> JPEG polling,
/// audio_only -> indicator tile.
class CameraLiveView extends ConsumerStatefulWidget {
  const CameraLiveView({
    super.key,
    required this.camera,
    this.showOverlay = true,
  });

  final Camera camera;
  final bool showOverlay;

  @override
  ConsumerState<CameraLiveView> createState() => _CameraLiveViewState();
}

class _CameraLiveViewState extends ConsumerState<CameraLiveView> {
  bool _webrtcFailed = false;

  /// MediaMTX publishes under the last path segment of the stream URL.
  String? get _streamName {
    final url = widget.camera.streamUrl;
    if (url == null || url.isEmpty) return null;
    final trimmed = url.replaceAll(RegExp(r'/+$'), '');
    final idx = trimmed.lastIndexOf('/');
    return idx >= 0 ? trimmed.substring(idx + 1) : trimmed;
  }

  /// MediaMTX lives on the server host; WebRTC on :8889, HLS on :8888.
  String? _mediamtxUrl(int port, String suffix) {
    final base = ref.read(serverConfigProvider).baseUrl;
    final name = _streamName;
    if (base == null || name == null) return null;
    final uri = Uri.parse(base);
    return '${uri.scheme}://${uri.host}:$port/$name$suffix';
  }

  @override
  Widget build(BuildContext context) {
    if (!widget.camera.online || !widget.camera.enabled) {
      return _placeholder(Icons.videocam_off_outlined, 'Offline');
    }

    final Widget video = switch (widget.camera.streamType) {
      'audio_only' => _placeholder(Icons.mic, 'Audio only', accent: true),
      'file' || 'hls' || 'http_mjpeg' when _looksLikeHttpVideo =>
        _FileVideoView(url: widget.camera.streamUrl!),
      'webcam' || 'http_snapshot' => _FramePollView(cameraId: widget.camera.id),
      _ => _rtspView(),
    };

    return Stack(
      fit: StackFit.expand,
      children: [
        video,
        if (widget.showOverlay) DetectionOverlay(cameraId: widget.camera.id),
      ],
    );
  }

  bool get _looksLikeHttpVideo =>
      widget.camera.streamUrl?.startsWith('http') ?? false;

  Widget _rtspView() {
    if (!_webrtcFailed) {
      final whep = _mediamtxUrl(8889, '/whep');
      if (whep != null) {
        return WhepPlayer(
          key: ValueKey(whep),
          whepUrl: whep,
          onFailed: () => setState(() => _webrtcFailed = true),
        );
      }
    }
    final hls = _mediamtxUrl(8888, '/index.m3u8');
    if (hls != null) return _FileVideoView(url: hls, live: true);
    return _FramePollView(cameraId: widget.camera.id);
  }

  Widget _placeholder(IconData icon, String label, {bool accent = false}) {
    return Container(
      color: NurbyColors.card,
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon,
                size: 32,
                color: accent ? NurbyColors.accent : NurbyColors.mutedForeground),
            const SizedBox(height: 6),
            Text(label,
                style: const TextStyle(
                    color: NurbyColors.mutedForeground, fontSize: 12)),
          ],
        ),
      ),
    );
  }
}

/// Direct playback for file/HTTP(S)/HLS URLs (demo clips, remote MP4s).
class _FileVideoView extends StatefulWidget {
  const _FileVideoView({required this.url, this.live = false});
  final String url;
  final bool live;

  @override
  State<_FileVideoView> createState() => _FileVideoViewState();
}

class _FileVideoViewState extends State<_FileVideoView> {
  late VideoPlayerController _controller;
  bool _ready = false;
  bool _error = false;

  @override
  void initState() {
    super.initState();
    _controller = VideoPlayerController.networkUrl(Uri.parse(widget.url))
      ..setVolume(0)
      ..setLooping(!widget.live);
    _controller.initialize().then((_) {
      if (!mounted) return;
      _controller.play();
      setState(() => _ready = true);
    }).catchError((_) {
      if (mounted) setState(() => _error = true);
    });
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (_error) {
      return const Center(
        child: Icon(Icons.error_outline, color: NurbyColors.mutedForeground),
      );
    }
    if (!_ready) {
      return const Center(
        child: SizedBox(
          width: 24,
          height: 24,
          child: CircularProgressIndicator(strokeWidth: 2),
        ),
      );
    }
    return FittedBox(
      fit: BoxFit.cover,
      clipBehavior: Clip.hardEdge,
      child: SizedBox(
        width: _controller.value.size.width,
        height: _controller.value.size.height,
        child: VideoPlayer(_controller),
      ),
    );
  }
}

/// ~1fps JPEG polling of the cached frame endpoint (webcam/snapshot cameras).
class _FramePollView extends ConsumerStatefulWidget {
  const _FramePollView({required this.cameraId});
  final String cameraId;

  @override
  ConsumerState<_FramePollView> createState() => _FramePollViewState();
}

class _FramePollViewState extends ConsumerState<_FramePollView> {
  Timer? _timer;
  int _tick = 0;

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() => _tick++);
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final repo = ref.watch(cameraRepoProvider);
    final url = '${repo.frameUrl(widget.cameraId)}&t=$_tick';
    return Image.network(
      url,
      fit: BoxFit.cover,
      gaplessPlayback: true,
      errorBuilder: (_, __, ___) => const Center(
        child: Icon(Icons.image_not_supported_outlined,
            color: NurbyColors.mutedForeground),
      ),
    );
  }
}
