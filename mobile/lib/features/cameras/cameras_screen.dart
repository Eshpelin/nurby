import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../models/models.dart';
import 'add_camera_sheet.dart';
import 'live_view.dart';

/// Apply a ReorderableListView drag.
///
/// The framework reports `to` as an index in the list *before* the
/// dragged item is removed, so moving an item downwards lands one slot
/// short unless that is accounted for. Pure, so the off-by-one is
/// testable without a gesture.
List<T> reorderList<T>(List<T> items, int from, int to) {
  final next = [...items];
  final item = next.removeAt(from);
  next.insert(from < to ? to - 1 : to, item);
  return next;
}

/// Home tab: live camera wall (mirrors the web dashboard grid).
class CamerasScreen extends ConsumerStatefulWidget {
  const CamerasScreen({super.key});

  @override
  ConsumerState<CamerasScreen> createState() => _CamerasScreenState();
}

class _CamerasScreenState extends ConsumerState<CamerasScreen> {
  bool _reordering = false;

  /// Order held locally while reordering, so a drag is not fighting a
  /// refresh from the server mid-gesture.
  List<Camera>? _draft;

  Future<void> _saveOrder(List<Camera> ordered) async {
    try {
      await ref
          .read(cameraRepoProvider)
          .reorder([for (final c in ordered) c.id]);
      ref.invalidate(camerasProvider);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
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
          if ((cameras.value?.length ?? 0) > 1)
            IconButton(
              tooltip: _reordering ? 'Done' : 'Reorder',
              icon: Icon(_reordering ? Icons.check : Icons.swap_vert),
              onPressed: () {
                if (_reordering && _draft != null) _saveOrder(_draft!);
                setState(() {
                  _reordering = !_reordering;
                  _draft = null;
                });
              },
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
          final sorted = _draft ??
              ([...list]..sort((a, b) =>
                  (a.displayOrder ?? 999).compareTo(b.displayOrder ?? 999)));
          if (_reordering) {
            // Live tiles are replaced by plain rows while dragging: a
            // grid of moving video is unreadable, and the only question
            // here is which camera goes where.
            return ReorderableListView.builder(
              padding: const EdgeInsets.all(12),
              itemCount: sorted.length,
              onReorder: (from, to) {
                setState(() => _draft = reorderList(sorted, from, to));
              },
              itemBuilder: (context, i) => Card(
                key: ValueKey(sorted[i].id),
                margin: const EdgeInsets.only(bottom: 8),
                child: ListTile(
                  leading: const Icon(Icons.drag_handle,
                      color: NurbyColors.mutedForeground),
                  title: Text(sorted[i].name),
                ),
              ),
            );
          }
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
