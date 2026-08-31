import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';

/// A conversation happening right now at one of the household's cameras.
///
/// This is the phone half of the handoff design. The agent holds the line
/// for a few seconds so a visitor is not left at a silent door, a push
/// arrives, and whoever picks up their phone can read what has been said
/// and answer in their own words.
///
/// Renders nothing when no conversation is open. It is a live alert, not
/// a section header, and an empty box saying "no conversations" would be
/// noise on a screen someone checks all day.
class LiveConversationCard extends ConsumerStatefulWidget {
  const LiveConversationCard({super.key, this.pollInterval = const Duration(seconds: 3)});

  /// A doorstep exchange lasts seconds, so this polls faster than the
  /// rest of the app. The widget stops as soon as nothing is live.
  final Duration pollInterval;

  @override
  ConsumerState<LiveConversationCard> createState() => _LiveConversationCardState();
}

class _LiveConversationCardState extends ConsumerState<LiveConversationCard> {
  Timer? _timer;
  Map<String, dynamic>? _session;
  final _draft = TextEditingController();
  bool _busy = false;
  String? _note;

  @override
  void initState() {
    super.initState();
    _poll();
    _timer = Timer.periodic(widget.pollInterval, (_) => _poll());
  }

  @override
  void dispose() {
    _timer?.cancel();
    _draft.dispose();
    super.dispose();
  }

  Future<void> _poll() async {
    try {
      final repo = ref.read(voiceRepoProvider);
      final live = await repo.liveSessions();
      if (!mounted) return;
      if (live.isEmpty) {
        setState(() => _session = null);
        return;
      }
      // Fetch the detail so the card shows the exchange rather than a row.
      final detail = await repo.session(live.first['id'] as String);
      if (!mounted) return;
      setState(() => _session = detail);
    } catch (_) {
      // A failed poll is not worth surfacing. The next one is seconds
      // away, and an error banner on a live doorbell would be noise.
    }
  }

  Future<void> _takeOver() async {
    final session = _session;
    if (session == null) return;
    setState(() => _busy = true);
    try {
      final body = await ref.read(voiceRepoProvider).takeOver(session['id'] as String);
      if (!mounted) return;
      setState(() => _note = body['took_over'] == true
          ? 'You have the conversation. The camera has stopped answering.'
          : 'Already ended: ${body['reason'] ?? 'unknown'}.');
      await _poll();
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _say() async {
    final session = _session;
    final text = _draft.text.trim();
    if (session == null || text.isEmpty) return;
    setState(() => _busy = true);
    try {
      final body =
          await ref.read(voiceRepoProvider).say(session['id'] as String, text);
      if (!mounted) return;
      final spoken = body['spoken'] == true;
      setState(() {
        _note = spoken ? null : 'Not played: ${body['reason'] ?? 'unknown'}';
        if (spoken) _draft.clear();
      });
      await _poll();
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final session = _session;
    if (session == null) return const SizedBox.shrink();

    final scheme = Theme.of(context).colorScheme;
    final transcript = (session['transcript'] as List? ?? [])
        .whereType<Map>()
        .map((t) => t.cast<String, dynamic>())
        .toList();
    final handedOff = session['handed_off'] == true;
    final refusals = (session['refusals'] as List? ?? []).length;

    return Card(
      margin: const EdgeInsets.fromLTRB(12, 12, 12, 4),
      color: scheme.tertiaryContainer.withValues(alpha: 0.35),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.record_voice_over, size: 18, color: scheme.tertiary),
                const SizedBox(width: 8),
                const Expanded(
                  child: Text('Someone is at your door',
                      style: TextStyle(fontWeight: FontWeight.w600)),
                ),
                if (!handedOff)
                  TextButton(
                    onPressed: _busy ? null : _takeOver,
                    child: const Text('Take over'),
                  ),
              ],
            ),
            const SizedBox(height: 8),
            Container(
              constraints: const BoxConstraints(maxHeight: 180),
              decoration: BoxDecoration(
                border: Border.all(color: scheme.outlineVariant),
                borderRadius: BorderRadius.circular(8),
              ),
              padding: const EdgeInsets.all(8),
              child: transcript.isEmpty
                  ? const Text('Listening.', style: TextStyle(fontSize: 12))
                  : ListView(
                      shrinkWrap: true,
                      reverse: true,
                      children: transcript.reversed.map((turn) {
                        final visitor = turn['speaker'] == 'visitor';
                        final held = turn['status'] == 'suppressed';
                        return Padding(
                          padding: const EdgeInsets.symmetric(vertical: 2),
                          child: RichText(
                            text: TextSpan(
                              style: DefaultTextStyle.of(context)
                                  .style
                                  .copyWith(fontSize: 12),
                              children: [
                                TextSpan(
                                  text: visitor ? 'Visitor: ' : 'Camera: ',
                                  style: TextStyle(
                                    color: visitor
                                        ? scheme.onSurfaceVariant
                                        : scheme.primary,
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                                TextSpan(text: '${turn['text']}'),
                                if (held)
                                  TextSpan(
                                    text: '  (held back)',
                                    style: TextStyle(
                                        color: scheme.tertiary, fontSize: 11),
                                  ),
                              ],
                            ),
                          ),
                        );
                      }).toList(),
                    ),
            ),
            const SizedBox(height: 8),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _draft,
                    maxLength: 240,
                    textInputAction: TextInputAction.send,
                    onSubmitted: (_) => _say(),
                    decoration: const InputDecoration(
                      hintText: 'Say something to them.',
                      counterText: '',
                      isDense: true,
                      border: OutlineInputBorder(),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                FilledButton(
                  onPressed: _busy ? null : _say,
                  child: const Text('Speak'),
                ),
              ],
            ),
            if (_note != null)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(_note!, style: const TextStyle(fontSize: 12)),
              ),
            if (refusals > 0)
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Text(
                  'The camera held back $refusals '
                  '${refusals == 1 ? 'reply' : 'replies'} that would have '
                  'given something away.',
                  style: TextStyle(fontSize: 11, color: scheme.onSurfaceVariant),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
