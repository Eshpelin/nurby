import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';

/// Notes on one event (issue #167): the household's shared record of what
/// they concluded. Lives in the event detail sheet.
final eventNotesProvider =
    FutureProvider.family<List<Map<String, dynamic>>, String>(
        (ref, eventId) => ref.watch(eventRepoProvider).notes(eventId));

/// The mute durations offered. Bounded by the server's 60s to 24h.
const kMuteChoices = [
  (Duration(minutes: 10), '10 minutes'),
  (Duration(hours: 1), '1 hour'),
  (Duration(hours: 8), '8 hours'),
  (Duration(hours: 24), 'A day'),
];

class EventNotes extends ConsumerStatefulWidget {
  const EventNotes({super.key, required this.eventId});

  final String eventId;

  @override
  ConsumerState<EventNotes> createState() => _EventNotesState();
}

class _EventNotesState extends ConsumerState<EventNotes> {
  final _controller = TextEditingController();
  bool _busy = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _add() async {
    final text = _controller.text.trim();
    if (text.isEmpty) return;
    setState(() => _busy = true);
    try {
      await ref.read(eventRepoProvider).addNote(widget.eventId, text);
      _controller.clear();
      ref.invalidate(eventNotesProvider(widget.eventId));
    } catch (e) {
      if (mounted) {
        // A connectivity failure was queued by the repository. Say so
        // rather than showing the raw error: the note is not lost.
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text((e is DioException && isConnectivityError(e))
                ? 'Offline. The note will be saved when you reconnect.'
                : apiErrorMessage(e))));
        if ((e is DioException && isConnectivityError(e))) _controller.clear();
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _delete(String noteId) async {
    try {
      await ref.read(eventRepoProvider).deleteNote(widget.eventId, noteId);
      ref.invalidate(eventNotesProvider(widget.eventId));
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(eventNotesProvider(widget.eventId));

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('NOTES',
            style: TextStyle(
                fontFamily: 'Menlo',
                fontSize: 10,
                letterSpacing: 1.4,
                color: NurbyColors.accent,
                fontWeight: FontWeight.w600)),
        const SizedBox(height: 8),
        async.when(
          loading: () => const LinearProgressIndicator(),
          error: (e, _) => Text(apiErrorMessage(e), style: _sub),
          data: (notes) => notes.isEmpty
              ? const Text('Nothing written down yet.', style: _sub)
              : Column(
                  children: [
                    for (final n in notes)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 8),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text('${n['text']}',
                                      style: const TextStyle(fontSize: 13)),
                                  Text(
                                    [
                                      // A note from the Telegram bot
                                      // reads differently from one typed
                                      // here, and the source says which.
                                      n['author_display_name'] ??
                                          (n['source'] == 'telegram'
                                              ? 'via Telegram'
                                              : 'someone'),
                                      if (n['created_at'] != null)
                                        DateFormat('MMM d, HH:mm').format(
                                            DateTime.parse('${n['created_at']}')
                                                .toLocal()),
                                    ].join(' · '),
                                    style: _sub,
                                  ),
                                ],
                              ),
                            ),
                            IconButton(
                              icon: const Icon(Icons.close, size: 16),
                              visualDensity: VisualDensity.compact,
                              onPressed: () => _delete('${n['id']}'),
                            ),
                          ],
                        ),
                      ),
                  ],
                ),
        ),
        const SizedBox(height: 4),
        Row(
          children: [
            Expanded(
              child: TextField(
                controller: _controller,
                textInputAction: TextInputAction.done,
                onSubmitted: (_) => _add(),
                decoration: const InputDecoration(
                  hintText: 'That was the plumber.',
                  isDense: true,
                  border: OutlineInputBorder(),
                ),
              ),
            ),
            const SizedBox(width: 8),
            OutlinedButton(
              onPressed: _busy ? null : _add,
              child: const Text('Add'),
            ),
          ],
        ),
      ],
    );
  }
}

const _sub = TextStyle(color: NurbyColors.mutedForeground, fontSize: 11);
