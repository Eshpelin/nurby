import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_webrtc/flutter_webrtc.dart';

/// WHEP (WebRTC-HTTP Egress Protocol) player for MediaMTX streams.
/// POSTs an SDP offer to {whepUrl} and renders the returned track.
class WhepPlayer extends StatefulWidget {
  const WhepPlayer({super.key, required this.whepUrl, this.onFailed});

  final String whepUrl;
  final VoidCallback? onFailed;

  @override
  State<WhepPlayer> createState() => _WhepPlayerState();
}

class _WhepPlayerState extends State<WhepPlayer> {
  final _renderer = RTCVideoRenderer();
  RTCPeerConnection? _pc;
  bool _connected = false;
  bool _failed = false;

  @override
  void initState() {
    super.initState();
    _start();
  }

  Future<void> _start() async {
    try {
      await _renderer.initialize();
      final pc = await createPeerConnection({
        'iceServers': [],
        'sdpSemantics': 'unified-plan',
      });
      _pc = pc;

      pc.onTrack = (event) {
        if (event.track.kind == 'video' && event.streams.isNotEmpty) {
          _renderer.srcObject = event.streams.first;
          if (mounted) setState(() => _connected = true);
        }
      };
      pc.onConnectionState = (state) {
        if (state == RTCPeerConnectionState.RTCPeerConnectionStateFailed ||
            state == RTCPeerConnectionState.RTCPeerConnectionStateClosed) {
          _fail();
        }
      };

      await pc.addTransceiver(
        kind: RTCRtpMediaType.RTCRtpMediaTypeVideo,
        init: RTCRtpTransceiverInit(direction: TransceiverDirection.RecvOnly),
      );
      await pc.addTransceiver(
        kind: RTCRtpMediaType.RTCRtpMediaTypeAudio,
        init: RTCRtpTransceiverInit(direction: TransceiverDirection.RecvOnly),
      );

      final offer = await pc.createOffer();
      await pc.setLocalDescription(offer);

      // Wait briefly for ICE gathering so the offer carries candidates
      // (MediaMTX WHEP expects a complete offer; trickle not used here).
      await _waitIceGathering(pc);
      final local = await pc.getLocalDescription();

      final res = await Dio().post<String>(
        widget.whepUrl,
        data: local!.sdp,
        options: Options(
          headers: {'Content-Type': 'application/sdp'},
          responseType: ResponseType.plain,
          validateStatus: (s) => s != null && s < 300,
          receiveTimeout: const Duration(seconds: 10),
        ),
      );
      await pc.setRemoteDescription(RTCSessionDescription(res.data, 'answer'));
    } catch (_) {
      _fail();
    }
  }

  Future<void> _waitIceGathering(RTCPeerConnection pc) async {
    if (pc.iceGatheringState ==
        RTCIceGatheringState.RTCIceGatheringStateComplete) {
      return;
    }
    final completer = Completer<void>();
    pc.onIceGatheringState = (state) {
      if (state == RTCIceGatheringState.RTCIceGatheringStateComplete &&
          !completer.isCompleted) {
        completer.complete();
      }
    };
    await completer.future.timeout(const Duration(seconds: 3), onTimeout: () {});
  }

  void _fail() {
    if (_failed || !mounted) return;
    _failed = true;
    widget.onFailed?.call();
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    _pc?.close();
    _renderer.srcObject = null;
    _renderer.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!_connected) {
      return const Center(
        child: SizedBox(
          width: 24,
          height: 24,
          child: CircularProgressIndicator(strokeWidth: 2),
        ),
      );
    }
    return RTCVideoView(
      _renderer,
      objectFit: RTCVideoViewObjectFit.RTCVideoViewObjectFitCover,
    );
  }
}
