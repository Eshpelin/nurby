import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../models/models.dart';
import 'add_camera_sheet.dart';
import 'live_view.dart';

/// Home tab: live camera wall (mirrors the web dashboard grid).
class CamerasScreen extends ConsumerWidget {
  const CamerasScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final cameras = ref.watch(camerasProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Cameras'),
        actions: [
          if (cameras.value != null)
            Padding(
              padding: const EdgeInsets.only(right: 4),
              child: Center(
                child: Text(
                  '${cameras.value!.where((c) => c.online).length}/${cameras.value!.length} online',
                  style: monoStyle,
                ),
              ),
            ),
          IconButton(
            icon: const Icon(Icons.add),
            onPressed: () => showAddCameraSheet(context, ref),
          ),
        ],
      ),
      body: cameras.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => _ErrorRetry(
          message: apiErrorMessage(e),
          onRetry: () => ref.invalidate(camerasProvider),
        ),
        data: (list) {
          if (list.isEmpty) return _EmptyState(ref: ref);
          final sorted = [...list]..sort((a, b) =>
              (a.displayOrder ?? 999).compareTo(b.displayOrder ?? 999));
          return RefreshIndicator(
            onRefresh: () async => ref.invalidate(camerasProvider),
            child: ListView.separated(
              padding: const EdgeInsets.all(12),
              itemCount: sorted.length,
              separatorBuilder: (_, __) => const SizedBox(height: 12),
              itemBuilder: (context, i) => _CameraTile(camera: sorted[i]),
            ),
          );
        },
      ),
    );
  }
}

class _CameraTile extends ConsumerWidget {
  const _CameraTile({required this.camera});
  final Camera camera;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return GestureDetector(
      onTap: () => context.go('/cameras/${camera.id}'),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(12),
        child: Container(
          decoration: BoxDecoration(
            border: Border.all(color: NurbyColors.border),
            borderRadius: BorderRadius.circular(12),
          ),
          child: AspectRatio(
            aspectRatio: 16 / 9,
            child: Stack(
              fit: StackFit.expand,
              children: [
                CameraLiveView(camera: camera),
                // Status pills
                Positioned(
                  top: 8,
                  left: 8,
                  right: 8,
                  child: Row(
                    children: [
                      _pill(
                        camera.online ? '● LIVE' : 'OFFLINE',
                        camera.online
                            ? NurbyColors.accent
                            : NurbyColors.mutedForeground,
                      ),
                      const SizedBox(width: 6),
                      if (camera.online && camera.recordingEnabled)
                        _pill('REC', const Color(0xFFF87171)),
                    ],
                  ),
                ),
                // Name gradient bar
                Positioned(
                  left: 0,
                  right: 0,
                  bottom: 0,
                  child: Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                    decoration: const BoxDecoration(
                      gradient: LinearGradient(
                        begin: Alignment.topCenter,
                        end: Alignment.bottomCenter,
                        colors: [Colors.transparent, Colors.black87],
                      ),
                    ),
                    child: Row(
                      children: [
                        Expanded(
                          child: Text(
                            camera.name,
                            style: const TextStyle(
                                fontWeight: FontWeight.w600, fontSize: 13),
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                        Text(camera.streamType, style: monoStyle),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _pill(String text, Color color) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
      decoration: BoxDecoration(
        color: Colors.black.withValues(alpha: 0.55),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(
        text,
        style: TextStyle(
          fontFamily: 'Menlo',
          fontSize: 9.5,
          fontWeight: FontWeight.w600,
          letterSpacing: 0.5,
          color: color,
        ),
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState({required this.ref});
  final WidgetRef ref;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.videocam_outlined,
                size: 48, color: NurbyColors.mutedForeground),
            const SizedBox(height: 16),
            const Text('No cameras yet',
                style: TextStyle(fontSize: 17, fontWeight: FontWeight.w600)),
            const SizedBox(height: 8),
            const Text(
              'Add an RTSP camera, or try the demo feed to see Nurby in action.',
              textAlign: TextAlign.center,
              style: TextStyle(color: NurbyColors.mutedForeground, fontSize: 13),
            ),
            const SizedBox(height: 24),
            FilledButton.icon(
              icon: const Icon(Icons.add),
              label: const Text('Add camera'),
              onPressed: () => showAddCameraSheet(context, ref),
            ),
          ],
        ),
      ),
    );
  }
}

class _ErrorRetry extends StatelessWidget {
  const _ErrorRetry({required this.message, required this.onRetry});
  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(message,
              style: const TextStyle(color: NurbyColors.mutedForeground)),
          const SizedBox(height: 12),
          TextButton(onPressed: onRetry, child: const Text('Retry')),
        ],
      ),
    );
  }
}
