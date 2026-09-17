import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../models/models.dart';

/// Structured alert feedback (#195). Acknowledging says "I saw this";
/// feedback says whether the alert was useful or even correct. Two
/// interactions: the rating and, for incorrect alerts, one optional
/// reason. Correcting re-rates in place — the server keeps one row per
/// reviewer.

const _kRatings = [
  ('useful', '👍 Useful'),
  ('correct_but_not_useful', '🤷 Correct, not useful'),
  ('incorrect', '👎 Incorrect'),
];

const _kReasons = [
  ('wrong_object', 'Wrong object'),
  ('wrong_person', 'Wrong person'),
  ('duplicate', 'Duplicate'),
  ('timing', 'Wrong timing'),
];

final eventFeedbackProvider =
    FutureProvider.family<List<EventFeedback>, String>(
        (ref, eventId) => ref.watch(eventRepoProvider).feedback(eventId));

class EventFeedbackPanel extends ConsumerStatefulWidget {
  const EventFeedbackPanel({super.key, required this.eventId});

  final String eventId;

  @override
  ConsumerState<EventFeedbackPanel> createState() => _EventFeedbackState();
}

class _EventFeedbackState extends ConsumerState<EventFeedbackPanel> {
  bool _busy = false;

  Future<void> _rate(String rating, {String? reason}) async {
    setState(() => _busy = true);
    try {
      await ref
          .read(eventRepoProvider)
          .setFeedback(widget.eventId, rating, reason: reason);
      ref.invalidate(eventFeedbackProvider(widget.eventId));
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text((e is DioException && isConnectivityError(e))
                ? 'Offline. Your feedback will be saved when you reconnect.'
                : apiErrorMessage(e))));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _withdraw() async {
    setState(() => _busy = true);
    try {
      await ref.read(eventRepoProvider).clearFeedback(widget.eventId);
      ref.invalidate(eventFeedbackProvider(widget.eventId));
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(eventFeedbackProvider(widget.eventId));
    final rows = async.value ?? const <EventFeedback>[];
    final myId = ref.watch(authProvider).user?.id;
    final mine = rows.where((r) => r.userId == myId).toList();
    final myRating = mine.isNotEmpty ? mine.first.rating : null;
    final myReason = mine.isNotEmpty ? mine.first.reason : null;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Was this alert useful?',
            style: TextStyle(fontSize: 12, color: NurbyColors.mutedForeground)),
        const SizedBox(height: 6),
        Wrap(
          spacing: 6,
          runSpacing: 6,
          children: [
            for (final (value, label) in _kRatings)
              ActionChip(
                avatar: myRating == value
                    ? const Icon(Icons.check, size: 14)
                    : null,
                label: Text(label, style: const TextStyle(fontSize: 12)),
                onPressed: _busy ? null : () => _rate(value),
              ),
          ],
        ),
        // The optional reason: asked only for incorrect ratings, answered
        // by one more tap, never required.
        if (myRating == 'incorrect' && myReason == null) ...[
          const SizedBox(height: 6),
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              for (final (value, label) in _kReasons)
                ActionChip(
                  label: Text(label, style: const TextStyle(fontSize: 12)),
                  onPressed: _busy ? null : () => _rate('incorrect', reason: value),
                ),
            ],
          ),
        ],
        if (rows.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 6),
            child: Text(
              '${rows.length} review${rows.length == 1 ? '' : 's'}'
              '${mine.isNotEmpty ? ' · yours saved' : ''}',
              style: TextStyle(fontSize: 11, color: NurbyColors.mutedForeground),
            ),
          ),
        if (mine.isNotEmpty)
          TextButton(
            onPressed: _busy ? null : _withdraw,
            style: TextButton.styleFrom(
              foregroundColor: NurbyColors.mutedForeground,
              minimumSize: const Size(0, 28),
              padding: const EdgeInsets.symmetric(horizontal: 4),
            ),
            child: const Text('Withdraw', style: TextStyle(fontSize: 12)),
          ),
      ],
    );
  }
}
