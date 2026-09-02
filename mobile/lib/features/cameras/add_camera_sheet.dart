import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';

/// How a discovered camera should read in the scan results.
///
/// Most cameras report an ONVIF name like "IPCamera", which tells a
/// household nothing when three of them answer the same scan. The
/// manufacturer and model are what distinguish them.
String discoveredTitle(Map<String, dynamic> device) {
  final made = [device['manufacturer'], device['model']]
      .whereType<String>()
      .map((x) => x.trim())
      .where((x) => x.isNotEmpty)
      .join(' ');
  if (made.isNotEmpty) return made;
  final name = (device['name'] as String?)?.trim() ?? '';
  return name.isEmpty ? 'Camera' : name;
}

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

  // Discovery state. `_scanned` distinguishes "not scanned yet" from
  // "scanned and found nothing", which want different words on screen.
  bool _scanning = false;
  bool _scanned = false;
  List<Map<String, dynamic>> _found = const [];

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

  Future<void> _scan() async {
    setState(() {
      _scanning = true;
      _error = null;
    });
    try {
      final found = await ref.read(cameraRepoProvider).discover();
      if (!mounted) return;
      setState(() {
        _found = found;
        _scanned = true;
      });
    } catch (e) {
      if (mounted) setState(() => _error = apiErrorMessage(e));
    } finally {
      if (mounted) setState(() => _scanning = false);
    }
  }

  /// Fill the form from a discovered device. Credentials are deliberately
  /// left blank: ONVIF discovery reports whether a camera wants them but
  /// never what they are, and a prefilled username nobody typed would be
  /// a guess presented as a fact.
  void _useDiscovered(Map<String, dynamic> d) {
    setState(() {
      _name.text = discoveredTitle(d);
      _url.text = d['stream_url'] as String? ?? '';
      _type = 'rtsp';
      _testResult = null;
      _error = null;
      _found = const [];
      _scanned = false;
    });
  }

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
            OutlinedButton.icon(
              icon: _scanning
                  ? const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.wifi_find_outlined),
              label: Text(_scanning ? 'Scanning' : 'Scan for cameras'),
              onPressed: _busy || _scanning ? null : _scan,
            ),
            if (_found.isNotEmpty) ...[
              const SizedBox(height: 8),
              for (final d in _found) DiscoveredTile(
                device: d,
                onUse: () => _useDiscovered(d),
              ),
            ] else if (_scanned) ...[
              const SizedBox(height: 8),
              const Text(
                // Discovery is WS-Discovery multicast from the Nurby
                // server, so a camera the phone can reach is not
                // necessarily one the server found. Saying where the scan
                // ran from is the difference between a useful message and
                // a dead end.
                'No cameras answered. The scan runs from the Nurby server, '
                'so the camera has to be on the same network as it. Cameras '
                'with ONVIF turned off will not answer either. You can '
                'still add one by hand below.',
                style: TextStyle(
                    color: NurbyColors.mutedForeground, fontSize: 12),
              ),
            ],
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


/// One camera the scan turned up.
class DiscoveredTile extends StatelessWidget {
  const DiscoveredTile({super.key, required this.device, required this.onUse});

  final Map<String, dynamic> device;
  final VoidCallback onUse;

  @override
  Widget build(BuildContext context) {
    final already = device['already_added'] == true;

    return Card(
      margin: const EdgeInsets.only(bottom: 6),
      child: ListTile(
        dense: true,
        title: Text(discoveredTitle(device),
            style: const TextStyle(fontSize: 13)),
        subtitle: Text(
          [
            '${device['ip']}:${device['port']}',
            if ((device['resolution'] as String?)?.isNotEmpty ?? false)
              '${device['resolution']}',
            if (device['auth_required'] == true) 'needs a login',
          ].join(' · '),
          style: const TextStyle(
              color: NurbyColors.mutedForeground, fontSize: 11),
        ),
        // A camera already in the household is shown rather than hidden,
        // so someone hunting for a camera they just plugged in can tell
        // "already added" from "not found".
        trailing: already
            ? const Text('Added',
                style: TextStyle(
                    color: NurbyColors.mutedForeground, fontSize: 11))
            : const Icon(Icons.add, size: 18, color: NurbyColors.accent),
        onTap: already ? null : onUse,
      ),
    );
  }
}
