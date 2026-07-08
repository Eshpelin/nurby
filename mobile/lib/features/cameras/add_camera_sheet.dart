import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';

void showAddCameraSheet(BuildContext context, WidgetRef ref) {
  showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    backgroundColor: NurbyColors.cardElevated,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
    ),
    builder: (_) => const _AddCameraSheet(),
  );
}

class _AddCameraSheet extends ConsumerStatefulWidget {
  const _AddCameraSheet();

  @override
  ConsumerState<_AddCameraSheet> createState() => _AddCameraSheetState();
}

class _AddCameraSheetState extends ConsumerState<_AddCameraSheet> {
  final _name = TextEditingController();
  final _url = TextEditingController();
  final _username = TextEditingController();
  final _password = TextEditingController();
  String _type = 'rtsp';
  bool _busy = false;
  String? _error;
  String? _testResult;

  @override
  void dispose() {
    _name.dispose();
    _url.dispose();
    _username.dispose();
    _password.dispose();
    super.dispose();
  }

  Map<String, dynamic> get _body => {
        'name': _name.text.trim(),
        'stream_url': _url.text.trim(),
        'stream_type': _type,
        if (_username.text.isNotEmpty) 'username': _username.text,
        if (_password.text.isNotEmpty) 'password': _password.text,
      };

  Future<void> _test() async {
    setState(() {
      _busy = true;
      _error = null;
      _testResult = null;
    });
    try {
      final res = await ref.read(cameraRepoProvider).testConnection({
        'stream_url': _url.text.trim(),
        'stream_type': _type,
        if (_username.text.isNotEmpty) 'username': _username.text,
        if (_password.text.isNotEmpty) 'password': _password.text,
      });
      setState(() {
        _testResult = res['ok'] == true
            ? 'Connected: ${res['width']}x${res['height']} @ ${res['fps'] ?? '?'}fps'
            : (res['hint'] as String? ?? res['error'] as String? ?? 'Failed');
      });
    } catch (e) {
      setState(() => _error = apiErrorMessage(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _create() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(cameraRepoProvider).create(_body);
      ref.invalidate(camerasProvider);
      if (mounted) Navigator.pop(context);
    } catch (e) {
      setState(() => _error = apiErrorMessage(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _createDemo() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(cameraRepoProvider).createDemo();
      ref.invalidate(camerasProvider);
      if (mounted) Navigator.pop(context);
    } catch (e) {
      setState(() => _error = apiErrorMessage(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(
        left: 20,
        right: 20,
        top: 20,
        bottom: MediaQuery.of(context).viewInsets.bottom + 24,
      ),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text('Add camera',
                style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
            const SizedBox(height: 16),
            OutlinedButton.icon(
              icon: const Icon(Icons.play_circle_outline,
                  color: NurbyColors.accent),
              label: const Text('Use demo feed',
                  style: TextStyle(color: NurbyColors.accent)),
              onPressed: _busy ? null : _createDemo,
            ),
            const SizedBox(height: 8),
            const Row(children: [
              Expanded(child: Divider()),
              Padding(
                padding: EdgeInsets.symmetric(horizontal: 12),
                child: Text('or',
                    style: TextStyle(
                        color: NurbyColors.mutedForeground, fontSize: 12)),
              ),
              Expanded(child: Divider()),
            ]),
            const SizedBox(height: 8),
            TextField(
              controller: _name,
              decoration: const InputDecoration(labelText: 'Name'),
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              value: _type,
              dropdownColor: NurbyColors.cardElevated,
              decoration: const InputDecoration(labelText: 'Stream type'),
              items: const [
                DropdownMenuItem(value: 'rtsp', child: Text('RTSP')),
                DropdownMenuItem(value: 'http_mjpeg', child: Text('HTTP MJPEG')),
                DropdownMenuItem(
                    value: 'http_snapshot', child: Text('HTTP snapshot')),
                DropdownMenuItem(value: 'hls', child: Text('HLS')),
                DropdownMenuItem(value: 'file', child: Text('Video file / URL')),
              ],
              onChanged: (v) => setState(() => _type = v ?? 'rtsp'),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _url,
              autocorrect: false,
              decoration: const InputDecoration(
                labelText: 'Stream URL',
                hintText: 'rtsp://192.168.1.10:554/stream1',
              ),
            ),
            const SizedBox(height: 12),
            Row(children: [
              Expanded(
                child: TextField(
                  controller: _username,
                  autocorrect: false,
                  decoration:
                      const InputDecoration(labelText: 'Username (optional)'),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: TextField(
                  controller: _password,
                  obscureText: true,
                  decoration:
                      const InputDecoration(labelText: 'Password (optional)'),
                ),
              ),
            ]),
            if (_testResult != null) ...[
              const SizedBox(height: 12),
              Text(_testResult!,
                  style: TextStyle(
                    color: _testResult!.startsWith('Connected')
                        ? NurbyColors.accent
                        : NurbyColors.warning,
                    fontSize: 13,
                  )),
            ],
            if (_error != null) ...[
              const SizedBox(height: 12),
              Text(_error!, style: const TextStyle(color: NurbyColors.danger)),
            ],
            const SizedBox(height: 16),
            Row(children: [
              Expanded(
                child: OutlinedButton(
                  onPressed: _busy ? null : _test,
                  child: const Text('Test connection'),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: FilledButton(
                  onPressed: _busy ? null : _create,
                  child: _busy
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2))
                      : const Text('Add'),
                ),
              ),
            ]),
          ],
        ),
      ),
    );
  }
}
