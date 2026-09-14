import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../models/models.dart';
import '../timeline/morning_recap_card.dart';
import '../voice/live_conversation_card.dart';

/// Home: is everything all right?
///
/// The one screen someone opens without a question in mind. Anything
/// happening right now comes first, then what needs their attention,
/// then the recap of the day so far. Nothing here is configured and
/// nothing is browsed; both of those live one tap away.
final _unreviewedProvider = FutureProvider<List<Event>>((ref) =>
    ref.watch(eventRepoProvider).history(acked: false, limit: 5));

class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final cameras = ref.watch(camerasProvider).value ?? const <Camera>[];
    final unreviewed = ref.watch(_unreviewedProvider);
    final online = cameras.where((c) => c.online).length;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Home'),
        actions: [
          IconButton(
            tooltip: 'Settings',
            icon: const Icon(Icons.settings_outlined),
            onPressed: () => context.push('/settings'),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(_unreviewedProvider);
          ref.invalidate(camerasProvider);
          ref.invalidate(morningRecapProvider);
        },
        child: ListView(
          padding: const EdgeInsets.only(bottom: 24),
          children: [
            // Happening now. The live card renders nothing when nothing
            // is live, which is most of the time.
            const LiveConversationCard(),

            // Cameras, as a strip. Tapping one goes to it; the header
            // goes to the grid.
            if (cameras.isNotEmpty) ...[
              _header(
                context,
                '$online of ${cameras.length} cameras online',
                'See all',
                () => context.go('/cameras'),
              ),
              SizedBox(
                height: 96,
                child: ListView(
                  scrollDirection: Axis.horizontal,
                  padding: const EdgeInsets.symmetric(horizontal: 12),
                  children: [
                    for (final c in cameras)
                      _CameraChip(
                        camera: c,
                        onTap: () => context.go('/cameras/${c.id}'),
                      ),
                  ],
                ),
              ),
            ],

            // Needs attention. Only unreviewed alerts, capped, with the
            // rest one tap away in Activity. The rules shortcut sits
            // here because "what should I be told about" is asked at
            // the moment someone is looking at what they were told.
            _header(
              context,
              'Needs attention',
              'All alerts',
              () => context.go('/activity?kind=alerts'),
            ),
            unreviewed.when(
              loading: () => const Padding(
                  padding: EdgeInsets.all(16), child: LinearProgressIndicator()),
              error: (e, _) => Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: Text(apiErrorMessage(e), style: _sub),
              ),
              data: (events) => events.isEmpty
                  ? const Padding(
                      padding: EdgeInsets.fromLTRB(16, 4, 16, 8),
                      child: Text('Nothing waiting for you.', style: _sub),
                    )
                  : Column(
                      children: [
                        for (final e in events)
                          ListTile(
                            dense: true,
                            leading: const Icon(Icons.notifications_active_outlined,
                                size: 18, color: NurbyColors.warning),
                            title: Text(e.ruleName,
                                style: const TextStyle(fontSize: 13)),
                            subtitle: Text(
                              DateFormat('EEE HH:mm').format(e.firedAt),
                              style: _sub,
                            ),
                            onTap: () => context.go('/activity?kind=alerts'),
                          ),
                      ],
                    ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 0, 12, 4),
              child: TextButton.icon(
                onPressed: () => context.push('/settings/rules'),
                icon: const Icon(Icons.tune, size: 16),
                label: const Text('What should I be told about?'),
              ),
            ),

            // The day so far.
            const MorningRecapCard(),
          ],
        ),
      ),
    );
  }

  Widget _header(BuildContext context, String title, String action, VoidCallback onAction) =>
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 18, 8, 4),
        child: Row(
          children: [
            Expanded(
              child: Text(title,
                  style: const TextStyle(fontWeight: FontWeight.w600)),
            ),
            TextButton(onPressed: onAction, child: Text(action)),
          ],
        ),
      );
}

class _CameraChip extends ConsumerWidget {
  const _CameraChip({required this.camera, required this.onTap});
  final Camera camera;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final url = ref.read(cameraRepoProvider).frameUrl(camera.id);
    return Padding(
      padding: const EdgeInsets.only(right: 8),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(10),
        child: SizedBox(
          width: 140,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(10),
                  child: Stack(
                    fit: StackFit.expand,
                    children: [
                      Image.network(url, fit: BoxFit.cover,
                          errorBuilder: (_, __, ___) => const ColoredBox(
                              color: NurbyColors.cardElevated,
                              child: Icon(Icons.videocam_off_outlined,
                                  color: NurbyColors.mutedForeground))),
                      Positioned(
                        left: 6, top: 6,
                        child: Container(
                          width: 8, height: 8,
                          decoration: BoxDecoration(
                            shape: BoxShape.circle,
                            color: camera.online ? NurbyColors.accent : NurbyColors.danger,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 4),
              Text(camera.name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: 12)),
            ],
          ),
        ),
      ),
    );
  }
}

const _sub = TextStyle(color: NurbyColors.mutedForeground, fontSize: 12);
