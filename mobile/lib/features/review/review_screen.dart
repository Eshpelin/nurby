import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';
import '../../core/theme.dart';

final reviewItemsProvider =
    FutureProvider.family<List<Map<String, dynamic>>, String>((ref, kind) {
      return ref.watch(reviewRepoProvider).list(kind: kind);
    });

/// Mobile projection of the single Review Center. It intentionally keeps
/// destructive/identity decisions explicit and lets the server enforce ACLs.
class ReviewScreen extends ConsumerStatefulWidget {
  const ReviewScreen({super.key});

  @override
  ConsumerState<ReviewScreen> createState() => _ReviewScreenState();
}

class _ReviewScreenState extends ConsumerState<ReviewScreen> {
  String _kind = 'all';
  final Map<String, Map<String, dynamic>> _details = {};
  String? _loadingDetail;

  Future<void> _toggleDetails(Map<String, dynamic> item) async {
    final id = item['source_id']?.toString();
    if (id == null || item['source_type'] != 'association') return;
    if (_details.containsKey(id)) {
      setState(() => _details.remove(id));
      return;
    }
    setState(() => _loadingDetail = id);
    try {
      final detail = await ref.read(reviewRepoProvider).detail(id);
      if (mounted) setState(() => _details[id] = detail);
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not load evidence: $error')),
        );
      }
    } finally {
      if (mounted) setState(() => _loadingDetail = null);
    }
  }

  Future<void> _decide(Map<String, dynamic> item, String decision) async {
    final id = item['source_id']?.toString();
    if (id == null || item['source_type'] != 'association') return;
    try {
      await ref.read(reviewRepoProvider).decideAssociation(id, decision);
      if (mounted) {
        ref.invalidate(reviewItemsProvider(_kind));
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text('Review marked $decision')));
      }
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Could not update review: $error')),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final items = ref.watch(reviewItemsProvider(_kind));
    return Scaffold(
      appBar: AppBar(title: const Text('Review Center')),
      body: Column(
        children: [
          SizedBox(
            height: 52,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              children: [
                _filter('all', 'All'),
                _filter('incident', 'Incidents'),
                _filter('alert', 'Alerts'),
                _filter('notification', 'Notifications'),
                _filter('suggestions', 'Suggestions'),
                _filter('camera_health', 'Camera health'),
              ],
            ),
          ),
          Expanded(
            child: items.when(
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (error, _) => _error(error),
              data:
                  (rows) => RefreshIndicator(
                    onRefresh:
                        () async => ref.invalidate(reviewItemsProvider(_kind)),
                    child:
                        rows.isEmpty
                            ? ListView(
                              physics: const AlwaysScrollableScrollPhysics(),
                              children: const [
                                Padding(
                                  padding: EdgeInsets.only(top: 96),
                                  child: Center(
                                    child: Text(
                                      'Nothing needs review',
                                      style: TextStyle(
                                        color: NurbyColors.mutedForeground,
                                      ),
                                    ),
                                  ),
                                ),
                              ],
                            )
                            : ListView.separated(
                              physics: const AlwaysScrollableScrollPhysics(),
                              padding: const EdgeInsets.fromLTRB(12, 4, 12, 24),
                              itemCount: rows.length,
                              separatorBuilder:
                                  (_, __) => const SizedBox(height: 8),
                              itemBuilder: (_, index) => _item(rows[index]),
                            ),
                  ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _filter(String value, String label) {
    final selected = _kind == value;
    return Padding(
      padding: const EdgeInsets.only(right: 8),
      child: ChoiceChip(
        label: Text(label),
        selected: selected,
        showCheckmark: false,
        selectedColor: NurbyColors.accent.withValues(alpha: 0.15),
        labelStyle: TextStyle(
          fontSize: 13,
          color: selected ? NurbyColors.accent : NurbyColors.foreground,
        ),
        side: BorderSide(
          color: selected ? NurbyColors.accent : NurbyColors.border,
        ),
        onSelected: (_) => setState(() => _kind = value),
      ),
    );
  }

  Widget _error(Object error) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Text(
          'Could not load reviews: $error',
          textAlign: TextAlign.center,
          style: const TextStyle(color: NurbyColors.mutedForeground),
        ),
      ),
    );
  }

  Widget _item(Map<String, dynamic> item) {
    final sourceType = item['source_type']?.toString() ?? 'review';
    final title = item['title']?.toString() ?? 'Review item';
    final summary = item['summary']?.toString();
    final camera = item['camera_name']?.toString();
    final status = item['status']?.toString();
    final association = sourceType == 'association';
    final sourceId = item['source_id']?.toString();
    final detail = sourceId == null ? null : _details[sourceId];
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Text(
                    title,
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                ),
                if (camera != null)
                  Text(
                    camera,
                    style: const TextStyle(
                      fontSize: 11,
                      color: NurbyColors.mutedForeground,
                    ),
                  ),
              ],
            ),
            if (summary != null && summary.isNotEmpty) ...[
              const SizedBox(height: 5),
              Text(
                summary,
                style: const TextStyle(
                  fontSize: 13,
                  color: NurbyColors.mutedForeground,
                ),
              ),
            ],
            const SizedBox(height: 5),
            Text(
              '${sourceType.replaceAll('_', ' ')}${status == null ? '' : ' · $status'}',
              style: const TextStyle(
                fontSize: 11,
                color: NurbyColors.mutedForeground,
              ),
            ),
            if (association) ...[
              const SizedBox(height: 8),
              TextButton.icon(
                onPressed:
                    _loadingDetail == sourceId
                        ? null
                        : () => _toggleDetails(item),
                icon: Icon(
                  detail == null
                      ? Icons.visibility_outlined
                      : Icons.visibility_off_outlined,
                ),
                label: Text(
                  _loadingDetail == sourceId
                      ? 'Loading evidence…'
                      : detail == null
                      ? 'View evidence'
                      : 'Hide evidence',
                ),
              ),
              if (detail != null) _evidence(detail),
              const SizedBox(height: 4),
              Wrap(
                spacing: 8,
                children: [
                  TextButton(
                    onPressed: () => _decide(item, 'confirm'),
                    child: const Text('Confirm'),
                  ),
                  TextButton(
                    onPressed: () => _decide(item, 'defer'),
                    child: const Text('Not now'),
                  ),
                  TextButton(
                    onPressed: () => _decide(item, 'ambiguous'),
                    child: const Text('Needs more evidence'),
                  ),
                  TextButton(
                    onPressed: () => _decide(item, 'reject'),
                    child: const Text('Reject'),
                  ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _evidence(Map<String, dynamic> detail) {
    final policy = detail['evidence_policy'];
    final evidence = detail['evidence'];
    final privacy = detail['privacy'];
    final supporting = detail['supporting_evidence_count'] ?? 0;
    final contradictory = detail['contradictory_evidence_count'] ?? 0;
    final confidence = detail['confidence_score'];
    final availability = detail['evidence_availability']?.toString();
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(9),
      decoration: BoxDecoration(
        color: NurbyColors.border.withValues(alpha: 0.25),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            'Evidence: $supporting supporting · $contradictory contradictory',
            style: const TextStyle(fontSize: 12),
          ),
          if (confidence is num)
            Text(
              'Confidence: ${(confidence * 100).round()}%',
              style: const TextStyle(
                fontSize: 12,
                color: NurbyColors.mutedForeground,
              ),
            ),
          if (policy is Map && policy['decision_recommendation'] != null)
            Text(
              'Guidance: ${policy['decision_recommendation']}',
              style: const TextStyle(
                fontSize: 12,
                color: NurbyColors.mutedForeground,
              ),
            ),
          if (availability != null)
            Text(
              'Source availability: $availability',
              style: const TextStyle(
                fontSize: 12,
                color: NurbyColors.mutedForeground,
              ),
            ),
          if (privacy is Map &&
              privacy['sensitive_evidence_restricted'] == true)
            const Text(
              'Sensitive evidence is restricted for this account.',
              style: TextStyle(fontSize: 12, color: Colors.amber),
            ),
          if (evidence is List)
            Text(
              '${evidence.length} evidence episode(s) available',
              style: const TextStyle(
                fontSize: 12,
                color: NurbyColors.mutedForeground,
              ),
            ),
        ],
      ),
    );
  }
}
