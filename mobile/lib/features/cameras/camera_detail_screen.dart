import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../models/models.dart';
import 'live_view.dart';

final _cameraProvider = FutureProvider.family<Camera, String>(
    (ref, id) => ref.watch(cameraRepoProvider).get(id));

final _cameraActivityProvider = FutureProvider.family<List<Observation>, String>(
    (ref, id) => ref.watch(observationRepoProvider).list(cameraId: id, limit: 30));

/// Camera detail: live view, PTZ, config toggles, recent activity.
class CameraDetailScreen extends ConsumerWidget {
  const CameraDetailScreen({super.key, required this.cameraId});

  final String cameraId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final cameraAsync = ref.watch(_cameraProvider(cameraId));

    return cameraAsync.when(
      loading: () => Scaffold(
        appBar: AppBar(),
        body: const Center(child: CircularProgressIndicator()),
      ),
      error: (e, _) => Scaffold(
        appBar: AppBar(),
        body: Center(child: Text(apiErrorMessage(e))),
      ),
      data: (camera) => _CameraDetailBody(camera: camera),
    );
  }
}

class _CameraDetailBody extends ConsumerStatefulWidget {
  const _CameraDetailBody({required this.camera});
  final Camera camera;

  @override
  ConsumerState<_CameraDetailBody> createState() => _CameraDetailBodyState();
}

class _CameraDetailBodyState extends ConsumerState<_CameraDetailBody> {
  bool _saving = false;

  Future<void> _patch(Map<String, dynamic> patch) async {
    setState(() => _saving = true);
    try {
      await ref.read(cameraRepoProvider).update(widget.camera.id, patch);
      ref.invalidate(_cameraProvider(widget.camera.id));
      ref.invalidate(camerasProvider);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _ptz(double pan, double tilt, double zoom) async {
    final api = ref.read(apiClientProvider);
    try {
      await api.postJson('/api/cameras/${widget.camera.id}/ptz/move',
          body: {'pan': pan, 'tilt': tilt, 'zoom': zoom});
      await Future<void>.delayed(const Duration(milliseconds: 400));
      await api.postJson('/api/cameras/${widget.camera.id}/ptz/stop');
    } catch (_) {
      // PTZ unsupported on this camera; ignore.
    }
  }

  Future<void> _delete() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: NurbyColors.cardElevated,
        title: const Text('Delete camera?'),
        content: Text(
            '"${widget.camera.name}" and its configuration will be removed.'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Cancel')),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Delete',
                style: TextStyle(color: NurbyColors.danger)),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    try {
      await ref.read(cameraRepoProvider).remove(widget.camera.id);
      ref.invalidate(camerasProvider);
      if (mounted) Navigator.pop(context);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final camera = widget.camera;
    final raw = camera.raw;
    final activity = ref.watch(_cameraActivityProvider(camera.id));
    final isRtsp = camera.streamType == 'rtsp';

    return Scaffold(
      appBar: AppBar(
        title: Text(camera.name),
        actions: [
          if (_saving)
            const Padding(
              padding: EdgeInsets.only(right: 16),
              child: Center(
                child: SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(strokeWidth: 2)),
              ),
            ),
          PopupMenuButton<String>(
            color: NurbyColors.cardElevated,
            onSelected: (v) {
              if (v == 'delete') _delete();
            },
            itemBuilder: (_) => const [
              PopupMenuItem(
                value: 'delete',
                child: Text('Delete camera',
                    style: TextStyle(color: NurbyColors.danger)),
              ),
            ],
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(12),
            child: AspectRatio(
              aspectRatio: 16 / 9,
              child: CameraLiveView(camera: camera),
            ),
          ),
          if (isRtsp) ...[
            const SizedBox(height: 10),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                _ptzButton(Icons.chevron_left, () => _ptz(-0.5, 0, 0)),
                _ptzButton(Icons.chevron_right, () => _ptz(0.5, 0, 0)),
                _ptzButton(Icons.keyboard_arrow_up, () => _ptz(0, 0.5, 0)),
                _ptzButton(Icons.keyboard_arrow_down, () => _ptz(0, -0.5, 0)),
                _ptzButton(Icons.add, () => _ptz(0, 0, 0.5)),
                _ptzButton(Icons.remove, () => _ptz(0, 0, -0.5)),
              ],
            ),
          ],
          _sectionLabel('DETECTION'),
          Card(
            child: Column(children: [
              SwitchListTile(
                title: const Text('Object detection'),
                subtitle: Text(
                  (raw['detect_classes'] as List?)?.join(', ') ?? 'all classes',
                  style: const TextStyle(
                      color: NurbyColors.mutedForeground, fontSize: 12),
                ),
                value: camera.detectObjects,
                activeColor: NurbyColors.accent,
                onChanged: (v) => _patch({'detect_objects': v}),
              ),
              SwitchListTile(
                title: const Text('Face recognition'),
                value: camera.detectFaces,
                activeColor: NurbyColors.accent,
                onChanged: (v) => _patch({'detect_faces': v}),
              ),
              SwitchListTile(
                title: const Text('License plates'),
                value: raw['detect_plates'] as bool? ?? false,
                activeColor: NurbyColors.accent,
                onChanged: (v) => _patch({'detect_plates': v}),
              ),
            ]),
          ),
          _sectionLabel('RECORDING'),
          Card(
            child: Column(children: [
              SwitchListTile(
                title: const Text('Recording'),
                subtitle: Text(
                  'mode: ${raw['recording_mode'] ?? 'objects'}',
                  style: const TextStyle(
                      color: NurbyColors.mutedForeground, fontSize: 12),
                ),
                value: camera.recordingEnabled,
                activeColor: NurbyColors.accent,
                onChanged: (v) => _patch({'recording_enabled': v}),
              ),
              ListTile(
                title: const Text('Retention'),
                subtitle: Text(
                  switch (raw['retention_mode']) {
                    'time' => '${raw['retention_days'] ?? '?'} days',
                    'size' => '${raw['retention_gb'] ?? '?'} GB',
                    _ => 'unlimited',
                  },
                  style: const TextStyle(
                      color: NurbyColors.mutedForeground, fontSize: 12),
                ),
              ),
            ]),
          ),
          _sectionLabel('AI ANALYSIS'),
          Card(
            child: ListTile(
              title: const Text('VLM prompt'),
              subtitle: Text(
                camera.vlmPrompt ?? 'default',
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                    color: NurbyColors.mutedForeground, fontSize: 12),
              ),
              trailing: const Icon(Icons.edit_outlined,
                  size: 18, color: NurbyColors.mutedForeground),
              onTap: () => _editVlmPrompt(camera),
            ),
          ),
          _sectionLabel('RECENT ACTIVITY'),
          activity.when(
            loading: () => const Padding(
              padding: EdgeInsets.all(24),
              child: Center(child: CircularProgressIndicator()),
            ),
            error: (e, _) => Padding(
              padding: const EdgeInsets.all(12),
              child: Text(apiErrorMessage(e),
                  style: const TextStyle(color: NurbyColors.mutedForeground)),
            ),
            data: (obs) => obs.isEmpty
                ? const Padding(
                    padding: EdgeInsets.all(12),
                    child: Text('No recent activity',
                        style: TextStyle(color: NurbyColors.mutedForeground)),
                  )
                : Column(
                    children: [
                      for (final o in obs.take(15))
                        Card(
                          margin: const EdgeInsets.only(bottom: 8),
                          child: ListTile(
                            leading: o.thumbnailPath != null
                                ? ClipRRect(
                                    borderRadius: BorderRadius.circular(6),
                                    child: Image.network(
                                      ref
                                          .read(observationRepoProvider)
                                          .thumbnailUrl(o.id),
                                      width: 64,
                                      height: 44,
                                      fit: BoxFit.cover,
                                      errorBuilder: (_, __, ___) =>
                                          const SizedBox(width: 64),
                                    ),
                                  )
                                : null,
                            title: Text(
                              o.vlmDescription ?? o.labels.join(', '),
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(fontSize: 13),
                            ),
                            subtitle: Text(
                                DateFormat('MMM d, HH:mm').format(o.startedAt),
                                style: monoStyle),
                          ),
                        ),
                    ],
                  ),
          ),
        ],
      ),
    );
  }

  Widget _ptzButton(IconData icon, VoidCallback onTap) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 4),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(10),
        child: Container(
          width: 44,
          height: 44,
          decoration: BoxDecoration(
            color: NurbyColors.card,
            border: Border.all(color: NurbyColors.border),
            borderRadius: BorderRadius.circular(10),
          ),
          child: Icon(icon, size: 20, color: NurbyColors.mutedForeground),
        ),
      ),
    );
  }

  Widget _sectionLabel(String text) {
    return Padding(
      padding: const EdgeInsets.only(top: 18, bottom: 8, left: 4),
      child: Text(
        text,
        style: const TextStyle(
          fontFamily: 'Menlo',
          fontSize: 10,
          letterSpacing: 1.4,
          color: NurbyColors.accent,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }

  Future<void> _editVlmPrompt(Camera camera) async {
    final controller = TextEditingController(text: camera.vlmPrompt ?? '');
    final result = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: NurbyColors.cardElevated,
        title: const Text('VLM prompt'),
        content: TextField(
          controller: controller,
          maxLines: 4,
          decoration:
              const InputDecoration(hintText: 'Describe what to watch for'),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
          TextButton(
              onPressed: () => Navigator.pop(ctx, controller.text),
              child: const Text('Save')),
        ],
      ),
    );
    if (result != null) await _patch({'vlm_prompt': result});
  }
}
