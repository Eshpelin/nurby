import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../models/models.dart';

final digestsListProvider = FutureProvider<List<DigestEntry>>(
    (ref) => ref.watch(digestRepoProvider).list());

class DigestsScreen extends ConsumerWidget {
  const DigestsScreen({super.key, this.embedded = false});

  /// Rendered inside the Activity screen: no Scaffold, no app bar.
  final bool embedded;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final list = ref.watch(digestsListProvider);
    final cameras = ref.watch(camerasProvider).value ?? const <Camera>[];
    final names = {for (final c in cameras) c.id: c.name};

    final body = RefreshIndicator(
        onRefresh: () async => ref.invalidate(digestsListProvider),
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
                onPressed: () => ref.invalidate(digestsListProvider),
                child: const Text('Retry'),
              ),
            ),
          ]),
          data: (items) => items.isEmpty
              ? ListView(children: const [
                  SizedBox(height: 96),
                  Icon(Icons.article_outlined,
                      size: 40, color: NurbyColors.mutedForeground),
                  SizedBox(height: 12),
                  Center(
                      child: Text('No recaps yet',
                          style: TextStyle(fontWeight: FontWeight.w600))),
                  SizedBox(height: 6),
                  Padding(
                    padding: EdgeInsets.symmetric(horizontal: 40),
                    child: Text(
                      'Nurby writes a periodic recap of what each camera saw. '
                      'The first one appears after a full period has passed.',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                          fontSize: 12, color: NurbyColors.mutedForeground),
                    ),
                  ),
                ])
              : ListView.builder(
                  itemCount: items.length,
                  itemBuilder: (_, i) => _DigestTile(
                    items[i],
                    // A digest with no camera covers the whole household.
                    items[i].cameraId == null
                        ? 'All cameras'
                        : names[items[i].cameraId] ?? 'A camera',
                  ),
                ),
        ),
      );
    if (embedded) return body;
    return Scaffold(
      // Called "camera summaries" on screen, not "digests": the morning
      // recap on the home tab is also a digest, and two features under
      // one word is how a household concludes one of them is broken.
      appBar: AppBar(title: const Text('Camera recaps')),
      body: body,
    );
  }
}

class _DigestTile extends StatelessWidget {
  const _DigestTile(this.digest, this.scope);

  final DigestEntry digest;
  final String scope;

  @override
  Widget build(BuildContext context) {
    final when = DateFormat('MMM d, HH:mm').format(digest.generatedAt);

    return Card(
      margin: const EdgeInsets.fromLTRB(12, 6, 12, 0),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(scope,
                      style: const TextStyle(fontWeight: FontWeight.w600)),
                ),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                  decoration: BoxDecoration(
                    color: NurbyColors.accent.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(digest.period,
                      style: const TextStyle(fontSize: 11)),
                ),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              '$when · ${digest.totalObservations} '
              '${digest.totalObservations == 1 ? 'observation' : 'observations'}',
              style: const TextStyle(
                  fontSize: 12, color: NurbyColors.mutedForeground),
            ),
            const SizedBox(height: 8),
            Text(digest.summary, style: const TextStyle(fontSize: 13)),
            if (digest.highlights.isNotEmpty) ...[
              const SizedBox(height: 8),
              ...digest.highlights.map(
                (h) => Padding(
                  padding: const EdgeInsets.only(top: 2),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('• ',
                          style: TextStyle(
                              fontSize: 12,
                              color: NurbyColors.mutedForeground)),
                      Expanded(
                        child: Text(h, style: const TextStyle(fontSize: 12)),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
