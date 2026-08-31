import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../models/models.dart';
import '../incidents/incidents_screen.dart' show formatDuration;

final journeysListProvider = FutureProvider<List<Journey>>(
    (ref) => ref.watch(journeyRepoProvider).list());

/// How a journey's subject should read.
///
/// Journeys are keyed the way incidents are, so the same care applies:
/// a person is a name, a cluster is an id nobody should be shown raw,
/// and appearance matching is stated as what it is.
String journeySubject(Journey j) {
  switch (j.subjectKind) {
    case 'person':
      return j.subjectKey.split(',').join(', ');
    case 'cluster':
      final short = j.subjectKey.split(',').first;
      return 'Recurring stranger ${short.substring(0, short.length.clamp(0, 8))}';
    case 'body':
      return 'Unrecognized person (matched by appearance)';
    default:
      return j.subjectKey.isEmpty ? 'Unknown' : j.subjectKey;
  }
}

class JourneysScreen extends ConsumerWidget {
  const JourneysScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final list = ref.watch(journeysListProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Journeys')),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(journeysListProvider),
        child: list.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => ListView(children: [
            const SizedBox(height: 96),
            Center(
                child: Text(apiErrorMessage(e),
                    textAlign: TextAlign.center,
                    style:
                        const TextStyle(color: NurbyColors.mutedForeground))),
            const SizedBox(height: 12),
            Center(
              child: OutlinedButton(
                onPressed: () => ref.invalidate(journeysListProvider),
                child: const Text('Retry'),
              ),
            ),
          ]),
          data: (items) => items.isEmpty
              ? ListView(children: const [
                  SizedBox(height: 96),
                  Icon(Icons.route_outlined,
                      size: 40, color: NurbyColors.mutedForeground),
                  SizedBox(height: 12),
                  Center(
                      child: Text('No journeys yet',
                          style: TextStyle(fontWeight: FontWeight.w600))),
                  SizedBox(height: 6),
                  Padding(
                    padding: EdgeInsets.symmetric(horizontal: 40),
                    child: Text(
                      'A journey is one subject followed across several cameras.',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                          fontSize: 12, color: NurbyColors.mutedForeground),
                    ),
                  ),
                ])
              : ListView.builder(
                  itemCount: items.length,
                  itemBuilder: (_, i) => _JourneyTile(items[i]),
                ),
        ),
      ),
    );
  }
}

class _JourneyTile extends StatelessWidget {
  const _JourneyTile(this.journey);

  final Journey journey;

  @override
  Widget build(BuildContext context) {
    final path = journey.cameraPath;
    final time = DateFormat('MMM d, HH:mm').format(journey.startedAt);
    final open = !journey.finalized;

    return Card(
      margin: const EdgeInsets.fromLTRB(12, 6, 12, 0),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                if (open)
                  Container(
                    width: 8,
                    height: 8,
                    margin: const EdgeInsets.only(right: 8),
                    decoration: const BoxDecoration(
                      color: NurbyColors.accent,
                      shape: BoxShape.circle,
                    ),
                  ),
                Expanded(
                  child: Text(journeySubject(journey),
                      style: const TextStyle(fontWeight: FontWeight.w600)),
                ),
                Text('${journey.camerasSeenCount} cameras',
                    style: const TextStyle(
                        fontSize: 12, color: NurbyColors.mutedForeground)),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              '$time · ${formatDuration(journey.lastSeenAt.difference(journey.startedAt))}',
              style: const TextStyle(
                  fontSize: 12, color: NurbyColors.mutedForeground),
            ),
            if (path.isNotEmpty) ...[
              const SizedBox(height: 8),
              // The path as the subject walked it. Wraps rather than
              // scrolls: a long journey should read as a long path, not
              // hide most of itself off-screen.
              Wrap(
                spacing: 4,
                runSpacing: 4,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  for (var i = 0; i < path.length; i++) ...[
                    if (i > 0)
                      const Icon(Icons.arrow_right_alt,
                          size: 14, color: NurbyColors.mutedForeground),
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 6, vertical: 2),
                      decoration: BoxDecoration(
                        color: NurbyColors.accent.withValues(alpha: 0.12),
                        borderRadius: BorderRadius.circular(4),
                      ),
                      child: Text(path[i], style: const TextStyle(fontSize: 11)),
                    ),
                  ],
                ],
              ),
            ],
            if (journey.summaryText != null) ...[
              const SizedBox(height: 8),
              Text(journey.summaryText!, style: const TextStyle(fontSize: 13)),
            ],
          ],
        ),
      ),
    );
  }
}
