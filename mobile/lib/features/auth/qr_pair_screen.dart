import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../../core/providers.dart';
import '../../core/theme.dart';

/// Scan the pairing QR code shown in the web app's Settings page.
/// The payload carries the server URL and a one-time login code, so a
/// single scan connects and signs in without typing anything.
class QrPairScreen extends ConsumerStatefulWidget {
  const QrPairScreen({super.key});

  @override
  ConsumerState<QrPairScreen> createState() => _QrPairScreenState();
}

class _QrPairScreenState extends ConsumerState<QrPairScreen> {
  final _controller = MobileScannerController(
    detectionSpeed: DetectionSpeed.noDuplicates,
    formats: const [BarcodeFormat.qrCode],
  );
  bool _claiming = false;
  String? _error;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _onDetect(BarcodeCapture capture) async {
    if (_claiming) return;
    final raw = capture.barcodes.firstOrNull?.rawValue;
    if (raw == null) return;

    final String url;
    final String code;
    try {
      final payload = jsonDecode(raw) as Map<String, dynamic>;
      url = payload['url'] as String;
      code = payload['code'] as String;
    } catch (_) {
      setState(() => _error = 'Not a Nurby pairing code');
      return;
    }

    setState(() {
      _claiming = true;
      _error = null;
    });
    try {
      await ref.read(authProvider.notifier).pairWithQr(url, code);
      // Router redirect takes over once the auth phase flips to loggedIn;
      // pop so the scanner is not left on the back stack.
      if (mounted) Navigator.of(context).maybePop();
    } catch (_) {
      if (mounted) {
        setState(() {
          _claiming = false;
          _error = 'Pairing failed. The code may have expired; '
              'generate a new one and try again.';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Scan QR code')),
      body: Stack(
        fit: StackFit.expand,
        children: [
          MobileScanner(controller: _controller, onDetect: _onDetect),
          // Framing hint.
          Center(
            child: Container(
              width: 240,
              height: 240,
              decoration: BoxDecoration(
                border: Border.all(color: Colors.white70, width: 2),
                borderRadius: BorderRadius.circular(16),
              ),
            ),
          ),
          Positioned(
            left: 24,
            right: 24,
            bottom: 40,
            child: Column(
              children: [
                if (_claiming)
                  const CircularProgressIndicator()
                else
                  const Text(
                    'In the web app, open Settings and tap '
                    '"Mobile app" to show a pairing code.',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: Colors.white),
                  ),
                if (_error != null) ...[
                  const SizedBox(height: 12),
                  Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 12, vertical: 8),
                    decoration: BoxDecoration(
                      color: Colors.black54,
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Text(_error!,
                        textAlign: TextAlign.center,
                        style: const TextStyle(color: NurbyColors.danger)),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}
