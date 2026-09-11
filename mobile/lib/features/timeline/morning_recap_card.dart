import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/providers.dart';
import '../../core/theme.dart';

/// The household's daily recap, on the home screen (issue #178).
///
/// This is the most phone-shaped content in the product: a few
/// sentences someone reads once a day, most likely in bed. It sits at
/// the top of the timeline rather than in the More menu because it is a
/// once-a-day read, not a place to navigate to.
///
/// Naming: the product also has per-camera "digests" (a separate screen
/// under More, from /api/digests). This card is /api/daily-digest, the
/// single household recap. On screen it is called the morning recap so
/// the two stop sharing a word.
final morningRecapProvider = FutureProvider<Map<String, dynamic>?>((ref) async {
  final j = await ref.watch(apiClientProvider).getJson('/api/daily-digest');
  return j is Map ? j.cast<String, dynamic>() : null;
});

/// One line from the facts when there is no narrative. Pure.
///
/// A camera-restricted user gets a facts-only digest (the narrative is
/// household-wide and would leak other cameras), and so does a household
/// whose AI provider is off. Both deserve a sentence, not a blank card.
String factsSummary(Map<String, dynamic> facts) {
  final parts = <String>[];
  final visitors = (facts['visitors'] as List? ?? const []).length;
  final unknown = (facts['unknown_visitors'] as num?)?.toInt() ?? 0;
  final incidents = (facts['incidents_count'] as num?)?.toInt() ?? 0;
  final packages = (facts['packages'] as num?)?.toInt() ?? 0;
  final vehicles = (facts['vehicles'] as num?)?.toInt() ?? 0;
  final fires = (facts['rule_fires'] as List? ?? const []).length;

  if (visitors > 0) parts.add('$visitors ${visitors == 1 ? 'visitor' : 'visitors'}');
  if (unknown > 0) parts.add('$unknown unknown');
  if (packages > 0) parts.add('$packages ${packages == 1 ? 'package' : 'packages'}');
  if (vehicles > 0) parts.add('$vehicles ${vehicles == 1 ? 'vehicle' : 'vehicles'}');
  if (incidents > 0) parts.add('$incidents ${incidents == 1 ? 'incident' : 'incidents'}');
  if (fires > 0) parts.add('$fires ${fires == 1 ? 'alert' : 'alerts'}');
  return parts.isEmpty ? 'A quiet day.' : parts.join(', ');
}

class MorningRecapCard extends ConsumerStatefulWidget {
  const MorningRecapCard({super.key});

  @override
  ConsumerState<MorningRecapCard> createState() => _MorningRecapCardState();
}

class _MorningRecapCardState extends ConsumerState<MorningRecapCard> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(morningRecapProvider);
    final d = async.value;
    // No recap yet is the normal state on a fresh install. Nothing to
    // say, so nothing is shown: an empty "no recap" box on the home
    // screen every morning would be noise.
    if (d == null) return const SizedBox.shrink();

    final text = (d['summary_text'] as String?)?.trim();
    final facts = (d['facts'] as Map? ?? const {}).cast<String, dynamic>();
    final body = (text?.isNotEmpty ?? false) ? text! : factsSummary(facts);
    final generated = DateTime.tryParse('${d['generated_at']}')?.toLocal();
    final long = body.length > 220;

    return Card(
      margin: const EdgeInsets.fromLTRB(12, 12, 12, 4),
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: long ? () => setState(() => _expanded = !_expanded) : null,
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Icon(Icons.wb_sunny_outlined,
                      size: 16, color: NurbyColors.accent),
                  const SizedBox(width: 8),
                  const Expanded(
                    child: Text('Morning recap',
                        style: TextStyle(fontWeight: FontWeight.w600)),
                  ),
                  if (generated != null)
                    Text(
                      DateFormat('EEE HH:mm').format(generated),
                      style: const TextStyle(
                          fontSize: 11, color: NurbyColors.mutedForeground),
                    ),
                ],
              ),
              const SizedBox(height: 8),
              Text(
                body,
                maxLines: _expanded ? null : 4,
                overflow: _expanded ? null : TextOverflow.ellipsis,
                style: const TextStyle(fontSize: 13, height: 1.4),
              ),
              if (long && !_expanded)
                const Padding(
                  padding: EdgeInsets.only(top: 4),
                  child: Text('Read more',
                      style: TextStyle(
                          fontSize: 12, color: NurbyColors.accent)),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
