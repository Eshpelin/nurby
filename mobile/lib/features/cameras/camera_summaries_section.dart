import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/providers.dart';
import '../../core/theme.dart';

/// What this camera concluded, over time (issue #175).
///
/// Summaries were already visible on mobile wherever something embedded
/// them: a timeline item, an incident, a conversation. What was missing
/// was the camera-scoped question, "what has the back door been
/// concluding this week", which is asked on the camera page and nowhere
/// else. So this lives on the camera page, as a section, rather than as
/// a fourth list screen under More that would show the same text the
/// timeline already shows.
final cameraSummariesProvider =
    FutureProvider.family<List<Map<String, dynamic>>, String>(
        (ref, cameraId) async => ((await ref
                .watch(apiClientProvider)
                .getJson('/api/summaries', query: {'camera_id': cameraId, 'limit': 20}))
            as List)
        .whereType<Map>()
        .map((s) => s.cast<String, dynamic>())
        .toList());

class CameraSummariesSection extends ConsumerWidget {
  const CameraSummariesSection({
    super.key,
    required this.cameraId,
    required this.sectionLabel,
  });

  final String cameraId;
  final Widget Function(String) sectionLabel;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(cameraSummariesProvider(cameraId));

    return async.when(
      loading: () => const SizedBox.shrink(),
      error: (_, __) => const SizedBox.shrink(),
      data: (rows) {
        // A camera with summaries off has none, and a section saying so
        // would only repeat what the Summaries toggle above already says.
        if (rows.isEmpty) return const SizedBox.shrink();
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            sectionLabel('WHAT IT CONCLUDED'),
            for (final s in rows.take(10))
              Card(
                margin: const EdgeInsets.only(bottom: 8),
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        [
                          _window(s),
                          // Periodic and event summaries answer different
                          // questions ("what happened this half hour" vs
                          // "what was that"), so the kind is shown.
                          s['kind'] == 'event' ? 'after an event' : 'on schedule',
                        ].join(' · '),
                        style: const TextStyle(
                            fontSize: 11, color: NurbyColors.mutedForeground),
                      ),
                      const SizedBox(height: 6),
                      Text('${s['summary_text'] ?? ''}',
                          style: const TextStyle(fontSize: 13, height: 1.35)),
                      if (((s['people_seen'] as List?)?.isNotEmpty ?? false)) ...[
                        const SizedBox(height: 6),
                        Text(
                          'Seen: ${(s['people_seen'] as List).join(', ')}',
                          style: const TextStyle(
                              fontSize: 11, color: NurbyColors.mutedForeground),
                        ),
                      ],
                    ],
                  ),
                ),
              ),
          ],
        );
      },
    );
  }

  static String _window(Map<String, dynamic> s) {
    final a = DateTime.tryParse('${s['started_at']}')?.toLocal();
    final b = DateTime.tryParse('${s['ended_at']}')?.toLocal();
    if (a == null || b == null) return '';
    final day = DateFormat('MMM d').format(a);
    return '$day, ${DateFormat('HH:mm').format(a)} to ${DateFormat('HH:mm').format(b)}';
  }
}
