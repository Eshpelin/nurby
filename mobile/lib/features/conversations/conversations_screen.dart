import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../models/models.dart';

final conversationsListProvider = FutureProvider<List<Conversation>>(
    (ref) => ref.watch(conversationRepoProvider).list());

/// The conversation plus the lines it was built from. Only the detail
/// endpoint carries transcripts, so this is fetched on open rather than
/// for every row in the list.
final conversationDetailProvider = FutureProvider.family<
    (Conversation, List<ConversationTranscript>),
    String>((ref, id) => ref.watch(conversationRepoProvider).get(id));

class ConversationsScreen extends ConsumerWidget {
  const ConversationsScreen({super.key, this.embedded = false});

  /// Rendered inside the Activity screen: no Scaffold, no app bar.
  final bool embedded;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final list = ref.watch(conversationsListProvider);
    final cameras = ref.watch(camerasProvider).value ?? const <Camera>[];
    final names = {for (final c in cameras) c.id: c.name};

    final body = RefreshIndicator(
        onRefresh: () async => ref.invalidate(conversationsListProvider),
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
                onPressed: () => ref.invalidate(conversationsListProvider),
                child: const Text('Retry'),
              ),
            ),
          ]),
          data: (items) => items.isEmpty
              ? ListView(children: const [
                  SizedBox(height: 96),
                  Icon(Icons.forum_outlined,
                      size: 40, color: NurbyColors.mutedForeground),
                  SizedBox(height: 12),
                  Center(
                      child: Text('No conversations yet',
                          style: TextStyle(fontWeight: FontWeight.w600))),
                  SizedBox(height: 6),
                  Padding(
                    padding: EdgeInsets.symmetric(horizontal: 40),
                    child: Text(
                      'Speech picked up near a camera is grouped into a conversation. '
                      'Audio capture has to be on for the camera.',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                          fontSize: 12, color: NurbyColors.mutedForeground),
                    ),
                  ),
                ])
              : ListView.builder(
                  itemCount: items.length,
                  itemBuilder: (_, i) => _ConversationTile(
                    items[i],
                    names[items[i].cameraId],
                  ),
                ),
        ),
      );
    if (embedded) return body;
    return Scaffold(
      appBar: AppBar(title: const Text('Conversations')),
      body: body,
    );
  }
}

class _ConversationTile extends ConsumerWidget {
  const _ConversationTile(this.conversation, this.cameraName);

  final Conversation conversation;
  final String? cameraName;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final time = DateFormat('MMM d, HH:mm').format(conversation.startedAt);
    final summary = conversation.summaryText ?? conversation.cleanedText;

    return Card(
      margin: const EdgeInsets.fromLTRB(12, 6, 12, 0),
      child: ExpansionTile(
        tilePadding: const EdgeInsets.symmetric(horizontal: 12),
        childrenPadding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
        title: Text(
          cameraName ?? 'Conversation',
          style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 14),
        ),
        subtitle: Text(
          [
            time,
            '${conversation.transcriptCount} '
                '${conversation.transcriptCount == 1 ? 'line' : 'lines'}',
            if (conversation.speakersSeen.isNotEmpty)
              conversation.speakersSeen.join(', '),
            if (!conversation.finalized) 'still going',
          ].join(' · '),
          style: const TextStyle(
              fontSize: 12, color: NurbyColors.mutedForeground),
        ),
        // Transcripts are fetched only when a row is opened. Pulling
        // every line for every conversation would make the list slow for
        // something most people never expand.
        onExpansionChanged: (open) {
          if (open) ref.read(conversationDetailProvider(conversation.id));
        },
        children: [
          if (summary != null) ...[
            Align(
              alignment: Alignment.centerLeft,
              child: Text(summary, style: const TextStyle(fontSize: 13)),
            ),
            const SizedBox(height: 10),
          ],
          _Transcripts(conversationId: conversation.id),
        ],
      ),
    );
  }
}

class _Transcripts extends ConsumerWidget {
  const _Transcripts({required this.conversationId});

  final String conversationId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final detail = ref.watch(conversationDetailProvider(conversationId));

    return detail.when(
      loading: () => const Padding(
        padding: EdgeInsets.symmetric(vertical: 12),
        child: Center(
          child: SizedBox(
              width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)),
        ),
      ),
      error: (e, _) => Text(apiErrorMessage(e),
          style: const TextStyle(
              fontSize: 12, color: NurbyColors.mutedForeground)),
      data: (pair) {
        final lines = pair.$2;
        if (lines.isEmpty) {
          return const Text('No transcript kept for this one.',
              style: TextStyle(
                  fontSize: 12, color: NurbyColors.mutedForeground));
        }
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: lines
              .map((line) => _TranscriptLine(
                    line: line,
                    conversationId: conversationId,
                  ))
              .toList(),
        );
      },
    );
  }
}


/// One line, with correction and deletion on long-press (issue #176).
///
/// Correction matters because STT gets names and addresses wrong, and a
/// wrong line feeds summaries, incidents and agent answers. Deletion
/// matters because a transcript is a recording of someone speaking near
/// a house. Both belong here, on the line, not in a separate manager.
class _TranscriptLine extends ConsumerWidget {
  const _TranscriptLine({required this.line, required this.conversationId});

  final ConversationTranscript line;
  final String conversationId;

  Future<void> _menu(BuildContext context, WidgetRef ref) async {
    final choice = await showModalBottomSheet<String>(
      context: context,
      backgroundColor: NurbyColors.cardElevated,
      builder: (ctx) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Padding(
              padding: const EdgeInsets.all(16),
              child: Text('"${line.text}"',
                  style: const TextStyle(
                      fontSize: 13, fontStyle: FontStyle.italic)),
            ),
            if (line.edited)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                child: Text('Heard as: "${line.originalText}"',
                    style: const TextStyle(
                        fontSize: 12, color: NurbyColors.mutedForeground)),
              ),
            ListTile(
              leading: const Icon(Icons.edit_outlined),
              title: const Text('Correct this line'),
              onTap: () => Navigator.pop(ctx, 'edit'),
            ),
            ListTile(
              leading: const Icon(Icons.delete_outline, color: NurbyColors.danger),
              title: const Text('Delete this line',
                  style: TextStyle(color: NurbyColors.danger)),
              onTap: () => Navigator.pop(ctx, 'delete'),
            ),
          ],
        ),
      ),
    );
    if (choice == null || !context.mounted) return;
    final repo = ref.read(transcriptRepoProvider);
    try {
      if (choice == 'edit') {
        final controller = TextEditingController(text: line.text);
        final text = await showDialog<String>(
          context: context,
          builder: (ctx) => AlertDialog(
            backgroundColor: NurbyColors.cardElevated,
            title: const Text('Correct the line'),
            content: TextField(controller: controller, maxLines: 3, autofocus: true),
            actions: [
              TextButton(
                  onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
              TextButton(
                  onPressed: () => Navigator.pop(ctx, controller.text.trim()),
                  child: const Text('Save')),
            ],
          ),
        );
        if (text == null || text.isEmpty || text == line.text) return;
        await repo.correct(line.id, text);
      } else {
        final ok = await showDialog<bool>(
          context: context,
          builder: (ctx) => AlertDialog(
            backgroundColor: NurbyColors.cardElevated,
            title: const Text('Delete this line?'),
            content: const Text(
                'It is removed from the transcript for good. Recaps '
                'already written from it are not rewritten.'),
            actions: [
              TextButton(
                  onPressed: () => Navigator.pop(ctx, false),
                  child: const Text('Cancel')),
              TextButton(
                onPressed: () => Navigator.pop(ctx, true),
                child: const Text('Delete',
                    style: TextStyle(color: NurbyColors.danger)),
              ),
            ],
          ),
        );
        if (ok != true) return;
        await repo.remove(line.id);
      }
      ref.invalidate(conversationDetailProvider(conversationId));
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) => InkWell(
        onLongPress: () => _menu(context, ref),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 3),
          child: RichText(
            text: TextSpan(
              style: DefaultTextStyle.of(context).style.copyWith(fontSize: 12),
              children: [
                TextSpan(
                  text: '${DateFormat('HH:mm:ss').format(line.startedAt)}  ',
                  style: const TextStyle(color: NurbyColors.mutedForeground),
                ),
                if (line.speakerName != null)
                  TextSpan(
                    text: '${line.speakerName}: ',
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                TextSpan(text: line.text),
                // A corrected line says so. Showing the fixed text as if
                // that is what was heard would be a quiet lie.
                if (line.edited)
                  const TextSpan(
                    text: '  (corrected)',
                    style: TextStyle(
                        fontSize: 11, color: NurbyColors.mutedForeground),
                  ),
              ],
            ),
          ),
        ),
      );
}
