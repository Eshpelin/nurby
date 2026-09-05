import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../models/models.dart';

/// Everything about one subject: header stats, a 24 hour activity
/// heatmap, a camera filter, and one feed mixing every kind of trace the
/// subject left (issue #163).
///
/// This is what makes the Incidents, Journeys and Conversations screens
/// worth having. Each of those names a subject and then dead-ends. The
/// question they provoke is "so what else has this person done", and
/// until now the phone could not answer it.

/// Query key: which subject, and which cameras to narrow to.
@immutable
class FollowQuery {
  const FollowQuery({
    required this.kind,
    required this.id,
    this.cameraIds = const [],
  });

  final String kind; // person | cluster
  final String id;
  final List<String> cameraIds;

  FollowQuery withCameras(List<String> ids) =>
      FollowQuery(kind: kind, id: id, cameraIds: ids);

  @override
  bool operator ==(Object other) =>
      other is FollowQuery &&
      other.kind == kind &&
      other.id == id &&
      other.cameraIds.join(',') == cameraIds.join(',');

  @override
  int get hashCode => Object.hash(kind, id, cameraIds.join(','));
}

final followProvider =
    FutureProvider.family<FollowBundle, FollowQuery>((ref, q) {
  final repo = ref.watch(followRepoProvider);
  return q.kind == 'cluster'
      ? repo.cluster(q.id, cameraIds: q.cameraIds)
      : repo.person(q.id, cameraIds: q.cameraIds);
});

class FollowScreen extends ConsumerStatefulWidget {
  const FollowScreen({super.key, required this.kind, required this.id});

  final String kind;
  final String id;

  @override
  ConsumerState<FollowScreen> createState() => _FollowScreenState();
}

class _FollowScreenState extends ConsumerState<FollowScreen> {
  List<String> _cameras = const [];

  @override
  Widget build(BuildContext context) {
    final query = FollowQuery(
        kind: widget.kind, id: widget.id, cameraIds: _cameras);
    final async = ref.watch(followProvider(query));

    return Scaffold(
      appBar: AppBar(title: Text(async.value?.subject.title ?? 'Activity')),
      body: async.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => ListView(children: [
          const SizedBox(height: 96),
          Center(
              child: Text(apiErrorMessage(e),
                  textAlign: TextAlign.center,
                  style: const TextStyle(color: NurbyColors.mutedForeground))),
          const SizedBox(height: 12),
          Center(
            child: OutlinedButton(
              onPressed: () => ref.invalidate(followProvider(query)),
              child: const Text('Retry'),
            ),
          ),
        ]),
        data: (bundle) => RefreshIndicator(
          onRefresh: () async => ref.invalidate(followProvider(query)),
          child: ListView(
            padding: const EdgeInsets.fromLTRB(12, 12, 12, 24),
            children: [
              _Header(subject: bundle.subject, stats: bundle.stats),
              const SizedBox(height: 12),
              if (bundle.stats.totalSightings > 0) ...[
                _Heatmap(hours: bundle.stats.hoursOfDay),
                const SizedBox(height: 12),
              ],
              if (bundle.stats.camerasSeen.isNotEmpty) ...[
                _CameraFilter(
                  cameras: bundle.stats.camerasSeen,
                  selected: _cameras,
                  onChanged: (ids) => setState(() => _cameras = ids),
                ),
                const SizedBox(height: 8),
              ],
              if (bundle.feed.isEmpty)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 48),
                  child: Center(
                    child: Text('Nothing in this window.',
                        style: TextStyle(color: NurbyColors.mutedForeground)),
                  ),
                )
              else
                for (final item in bundle.feed) _FeedTile(item: item),
            ],
          ),
        ),
      ),
    );
  }
}

class _Header extends StatelessWidget {
  const _Header({required this.subject, required this.stats});

  final FollowSubject subject;
  final FollowStats stats;

  @override
  Widget build(BuildContext context) {
    final fmt = DateFormat('MMM d, HH:mm');
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(subject.title,
                style: const TextStyle(
                    fontSize: 17, fontWeight: FontWeight.w600)),
            if (subject.subtitle?.isNotEmpty ?? false)
              Padding(
                padding: const EdgeInsets.only(top: 2),
                child: Text(subject.subtitle!, style: _sub),
              ),
            const SizedBox(height: 10),
            Wrap(
              spacing: 16,
              runSpacing: 8,
              children: [
                _Stat('${stats.totalSightings}', 'sightings'),
                _Stat('${stats.camerasSeen.length}', 'cameras'),
                if (stats.incidentsCount > 0)
                  _Stat('${stats.incidentsCount}', 'incidents'),
                if (stats.conversationsCount > 0)
                  _Stat('${stats.conversationsCount}', 'conversations'),
                if (stats.recordingsCount > 0)
                  _Stat('${stats.recordingsCount}', 'recordings'),
              ],
            ),
            if (stats.firstSeenAt != null && stats.lastSeenAt != null) ...[
              const SizedBox(height: 10),
              Text(
                'First seen ${fmt.format(stats.firstSeenAt!)} · '
                'last seen ${fmt.format(stats.lastSeenAt!)}',
                style: _sub,
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _Stat extends StatelessWidget {
  const _Stat(this.value, this.label);
  final String value;
  final String label;

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(value,
              style: const TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.w700,
                  color: NurbyColors.accent)),
          Text(label, style: _sub),
        ],
      );
}

/// Sightings by hour of day. Deliberately all 24 hours, including the
/// empty ones: the shape of when someone is around is the point, and a
/// chart that skipped quiet hours would compress a 3am visit next to a
/// 9am one and read as routine.
class _Heatmap extends StatelessWidget {
  const _Heatmap({required this.hours});

  final List<int> hours;

  @override
  Widget build(BuildContext context) {
    final peak = hours.fold<int>(0, (a, b) => b > a ? b : a);

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('When, by hour of day',
                style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
            const SizedBox(height: 10),
            SizedBox(
              height: 56,
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  for (var h = 0; h < 24; h++)
                    Expanded(
                      child: Tooltip(
                        message: '${h.toString().padLeft(2, '0')}:00 · '
                            '${hours[h]} '
                            '${hours[h] == 1 ? 'sighting' : 'sightings'}',
                        child: Padding(
                          padding: const EdgeInsets.symmetric(horizontal: 1),
                          child: Container(
                            // Always at least a hairline, so an empty
                            // hour reads as an hour with nothing in it
                            // rather than as a gap in the axis.
                            height: peak == 0
                                ? 2
                                : (2 + 46 * hours[h] / peak),
                            decoration: BoxDecoration(
                              color: hours[h] == 0
                                  ? NurbyColors.border
                                  : NurbyColors.accent.withValues(
                                      alpha: 0.35 + 0.65 * hours[h] / peak),
                              borderRadius: BorderRadius.circular(2),
                            ),
                          ),
                        ),
                      ),
                    ),
                ],
              ),
            ),
            const SizedBox(height: 4),
            const Row(
              children: [
                Text('00', style: _tiny),
                Spacer(),
                Text('06', style: _tiny),
                Spacer(),
                Text('12', style: _tiny),
                Spacer(),
                Text('18', style: _tiny),
                Spacer(),
                Text('23', style: _tiny),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _CameraFilter extends StatelessWidget {
  const _CameraFilter({
    required this.cameras,
    required this.selected,
    required this.onChanged,
  });

  final List<FollowCamera> cameras;
  final List<String> selected;
  final ValueChanged<List<String>> onChanged;

  @override
  Widget build(BuildContext context) => Wrap(
        spacing: 6,
        runSpacing: 6,
        children: [
          ChoiceChip(
            label: const Text('All cameras'),
            selected: selected.isEmpty,
            onSelected: (_) => onChanged(const []),
          ),
          for (final c in cameras)
            ChoiceChip(
              label: Text('${c.name} · ${c.count}'),
              selected: selected.contains(c.id),
              onSelected: (on) {
                final next = selected.where((id) => id != c.id).toList();
                if (on) next.add(c.id);
                onChanged(next);
              },
            ),
        ],
      );
}

class _FeedTile extends StatelessWidget {
  const _FeedTile({required this.item});

  final FollowItem item;

  @override
  Widget build(BuildContext context) {
    final time = DateFormat('MMM d, HH:mm').format(item.at);
    final (icon, title) = _describe(item);

    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: ListTile(
        dense: true,
        leading: Icon(icon, size: 20, color: NurbyColors.mutedForeground),
        title: Text(title,
            maxLines: 3,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(fontSize: 13)),
        subtitle: Text(
          [time, if (item.cameraName != null) item.cameraName!].join(' · '),
          style: _sub,
        ),
      ),
    );
  }

  /// One line per feed kind. The fields differ per kind, so each falls
  /// back to something true rather than to an empty tile.
  static (IconData, String) _describe(FollowItem i) {
    final r = i.raw;
    switch (i.kind) {
      case 'incident':
        final n = (r['occurrence_count'] as num?)?.toInt() ?? 0;
        return (
          Icons.inbox_outlined,
          r['summary_text'] as String? ??
              'Incident${n > 1 ? ', $n sightings' : ''}',
        );
      case 'conversation':
        final n = (r['transcript_count'] as num?)?.toInt() ?? 0;
        return (
          Icons.forum_outlined,
          (r['summary_text'] ?? r['cleaned_text']) as String? ??
              'Conversation, $n ${n == 1 ? 'line' : 'lines'}',
        );
      case 'transcript':
        return (Icons.record_voice_over_outlined,
            r['text'] as String? ?? 'Speech');
      case 'recording':
        final secs = (r['duration_seconds'] as num?)?.toInt();
        return (
          Icons.videocam_outlined,
          secs == null ? 'Recording' : 'Recording, ${_dur(secs)}',
        );
      default:
        return (
          Icons.visibility_outlined,
          r['vlm_description'] as String? ?? 'Seen',
        );
    }
  }

  static String _dur(int seconds) {
    if (seconds < 60) return '${seconds}s';
    final m = seconds ~/ 60;
    return m < 60 ? '${m}m' : '${m ~/ 60}h ${m % 60}m';
  }
}

const _sub = TextStyle(color: NurbyColors.mutedForeground, fontSize: 12);
const _tiny = TextStyle(color: NurbyColors.mutedForeground, fontSize: 10);
