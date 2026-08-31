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
  const ConversationsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final list = ref.watch(conversationsListProvider);
    final cameras = ref.watch(camerasProvider).value ?? const <Camera>[];
    final names = {for (final c in cameras) c.id: c.name};

    return Scaffold(
      appBar: AppBar(title: const Text('Conversations')),
      body: RefreshIndicator(
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
      ),
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
              .map((line) => Padding(
                    padding: const EdgeInsets.symmetric(vertical: 3),
                    child: RichText(
                      text: TextSpan(
                        style: DefaultTextStyle.of(context)
                            .style
                            .copyWith(fontSize: 12),
                        children: [
                          TextSpan(
                            text:
                                '${DateFormat('HH:mm:ss').format(line.startedAt)}  ',
                            style: const TextStyle(
                                color: NurbyColors.mutedForeground),
                          ),
                          if (line.speakerName != null)
                            TextSpan(
                              text: '${line.speakerName}: ',
                              style: const TextStyle(
                                  fontWeight: FontWeight.w600),
                            ),
                          TextSpan(text: line.text),
                        ],
                      ),
                    ),
                  ))
              .toList(),
        );
      },
    );
  }
}
