import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../models/models.dart';

/// Live bounding-box overlay fed by WS `detection` messages for one camera.
/// Boxes fade out after 3.5s of silence (matches web behavior).
class DetectionOverlay extends ConsumerStatefulWidget {
  const DetectionOverlay({super.key, required this.cameraId});

  final String cameraId;

  @override
  ConsumerState<DetectionOverlay> createState() => _DetectionOverlayState();
}

class _DetectionOverlayState extends ConsumerState<DetectionOverlay> {
  List<Detection> _detections = const [];
  double _frameW = 1920, _frameH = 1080;
  Timer? _fadeTimer;

  @override
  void dispose() {
    _fadeTimer?.cancel();
    super.dispose();
  }

  void _onMessage(Map<String, dynamic> msg) {
    if (msg['camera_id'] != widget.cameraId) return;
    final type = msg['type'];
    if (type != 'detection' && type != 'person_actions') return;

    final dets = <Detection>[];
    if (type == 'detection' && msg['detections'] is List) {
      for (final d in msg['detections'] as List) {
        if (d is! Map) continue;
        final m = d.cast<String, dynamic>();
        // Two shapes seen: {box: [x1,y1,x2,y2]} or flat x1..y2.
        if (m['box'] is List && (m['box'] as List).length == 4) {
          final b = (m['box'] as List).map((v) => (v as num).toDouble()).toList();
          dets.add(Detection(
            label: m['label'] as String? ?? '?',
            confidence: (m['confidence'] as num?)?.toDouble() ?? 0,
            x1: b[0], y1: b[1], x2: b[2], y2: b[3],
          ));
        } else {
          dets.add(Detection.fromJson(m));
        }
      }
    }
    if (msg['width'] is num) _frameW = (msg['width'] as num).toDouble();
    if (msg['height'] is num) _frameH = (msg['height'] as num).toDouble();

    if (dets.isNotEmpty || type == 'detection') {
      setState(() => _detections = dets);
      _fadeTimer?.cancel();
      _fadeTimer = Timer(const Duration(milliseconds: 3500), () {
        if (mounted) setState(() => _detections = const []);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    ref.listen(wsMessagesProvider, (_, next) {
      final msg = next.value;
      if (msg != null) _onMessage(msg);
    });

    if (_detections.isEmpty) return const SizedBox.shrink();
    return IgnorePointer(
      child: CustomPaint(
        size: Size.infinite,
        painter: _BoxPainter(_detections, _frameW, _frameH),
      ),
    );
  }
}

class _BoxPainter extends CustomPainter {
  _BoxPainter(this.detections, this.frameW, this.frameH);

  final List<Detection> detections;
  final double frameW, frameH;

  @override
  void paint(Canvas canvas, Size size) {
    final sx = size.width / frameW;
    final sy = size.height / frameH;

    for (final d in detections) {
      final isPerson = d.label == 'person' || d.personName != null;
      final color = isPerson ? NurbyColors.accent : const Color(0xFF3B82F6);
      final rect = Rect.fromLTRB(d.x1 * sx, d.y1 * sy, d.x2 * sx, d.y2 * sy);

      canvas.drawRect(
        rect,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 2
          ..color = color,
      );

      final label = d.personName ?? d.label;
      final tp = TextPainter(
        text: TextSpan(
          text: ' $label ${(d.confidence * 100).round()}% ',
          style: const TextStyle(
              color: Colors.black, fontSize: 11, fontWeight: FontWeight.w600),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      final labelTop = (rect.top - tp.height).clamp(0.0, size.height);
      canvas.drawRect(
        Rect.fromLTWH(rect.left, labelTop, tp.width, tp.height),
        Paint()..color = color,
      );
      tp.paint(canvas, Offset(rect.left, labelTop));
    }
  }

  @override
  bool shouldRepaint(_BoxPainter old) =>
      old.detections != detections || old.frameW != frameW || old.frameH != frameH;
}
