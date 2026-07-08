import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';

enum _ItemKind { user, assistant, tool, error }

class _ChatItem {
  _ChatItem(this.kind, this.text);
  final _ItemKind kind;
  String text;
  bool streaming = false;
}

/// Chat UI for the Nurby agent: POST /api/agent/ask then stream the run
/// over a per-run websocket.
class AskScreen extends ConsumerStatefulWidget {
  const AskScreen({super.key});

  @override
  ConsumerState<AskScreen> createState() => _AskScreenState();
}

class _AskScreenState extends ConsumerState<AskScreen> {
  final List<_ChatItem> _items = [];
  final _composer = TextEditingController();
  final _scroll = ScrollController();

  WebSocketChannel? _channel;
  StreamSubscription<dynamic>? _sub;
  bool _running = false;

  /// Assistant bubble currently receiving streamed deltas.
  _ChatItem? _current;

  @override
  void dispose() {
    _closeSocket();
    _composer.dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _closeSocket() {
    _sub?.cancel();
    _sub = null;
    _channel?.sink.close();
    _channel = null;
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scroll.hasClients) return;
      _scroll.animateTo(
        _scroll.position.maxScrollExtent,
        duration: const Duration(milliseconds: 200),
        curve: Curves.easeOut,
      );
    });
  }

  Future<void> _send() async {
    final question = _composer.text.trim();
    if (question.isEmpty || _running) return;
    _composer.clear();
    setState(() {
      _running = true;
      _items.add(_ChatItem(_ItemKind.user, question));
      _current = _ChatItem(_ItemKind.assistant, '')..streaming = true;
      _items.add(_current!);
    });
    _scrollToBottom();

    try {
      final api = ref.read(apiClientProvider);
      final j = await api.postJson('/api/agent/ask',
          body: {'question': question}) as Map;
      final wsUrl =
          j['ws_url'] as String? ?? '/ws/agent/${j['run_id'] as String? ?? ''}';
      final wsBase = ref.read(serverConfigProvider).wsBaseUrl;
      if (wsBase == null) {
        _finishWithError('No server configured');
        return;
      }
      final sep = wsUrl.contains('?') ? '&' : '?';
      final uri = Uri.parse('$wsBase$wsUrl${sep}token=${api.token ?? ''}');
      _channel = WebSocketChannel.connect(uri);
      _sub = _channel!.stream.listen(
        _onWsData,
        onError: (_) => _finishWithError('Connection error'),
        onDone: _onWsDone,
      );
    } catch (e) {
      _finishWithError(apiErrorMessage(e));
    }
  }

  void _ensureCurrent() {
    if (_current == null) {
      _current = _ChatItem(_ItemKind.assistant, '')..streaming = true;
      _items.add(_current!);
    }
  }

  void _onWsData(dynamic data) {
    if (!mounted) return;
    Map<String, dynamic>? msg;
    try {
      final decoded = jsonDecode(data as String);
      if (decoded is Map<String, dynamic>) msg = decoded;
    } catch (_) {
      return; // Non-JSON frame; ignore.
    }
    if (msg == null) return;

    switch (msg['type']) {
      case 'message_delta':
        final content = msg['content'] as String? ?? '';
        if (content.isEmpty) return;
        setState(() {
          _ensureCurrent();
          _current!.text += content;
        });
        _scrollToBottom();
      case 'tool_call':
        final name = msg['tool_name'] as String? ?? 'tool';
        setState(() {
          final tool = _ChatItem(_ItemKind.tool, name);
          if (_current != null && _current!.text.isEmpty) {
            // Keep the pending bubble after the tool line.
            _items.insert(_items.indexOf(_current!), tool);
          } else {
            // Text already streamed; start a fresh bubble after the tool.
            _items.add(tool);
            _current = _ChatItem(_ItemKind.assistant, '')..streaming = true;
            _items.add(_current!);
          }
        });
        _scrollToBottom();
      case 'tool_result':
        break; // Nothing to render.
      case 'completion':
        final answer = msg['answer'] as String? ?? '';
        setState(() {
          _ensureCurrent();
          if (answer.trim().isNotEmpty) _current!.text = answer;
          if (_current!.text.isEmpty) {
            _items.remove(_current);
          } else {
            _current!.streaming = false;
          }
          _current = null;
          _running = false;
        });
        _closeSocket();
        _scrollToBottom();
      case 'error':
        _finishWithError(msg['message'] as String? ?? 'Agent error');
    }
  }

  void _onWsDone() {
    if (!mounted || !_running) return;
    // Socket closed without a completion frame; finalize what we have.
    setState(() {
      if (_current != null) {
        if (_current!.text.isEmpty) {
          _items.remove(_current);
          _items.add(_ChatItem(_ItemKind.error, 'Connection closed'));
        } else {
          _current!.streaming = false;
        }
        _current = null;
      }
      _running = false;
    });
    _closeSocket();
  }

  void _finishWithError(String message) {
    _closeSocket();
    if (!mounted) return;
    setState(() {
      if (_current != null && _current!.text.isEmpty) {
        _items.remove(_current);
      } else {
        _current?.streaming = false;
      }
      _current = null;
      _items.add(_ChatItem(_ItemKind.error, message));
      _running = false;
    });
    _scrollToBottom();
  }

  // ---- History ----

  Future<List<Map<String, dynamic>>> _fetchRuns() async {
    final j = await ref.read(apiClientProvider).getJson('/api/agent/runs');
    final list = j is List ? j : (j as Map)['runs'] as List? ?? const [];
    return list.whereType<Map>().map((r) => r.cast<String, dynamic>()).toList();
  }

  void _showHistory() {
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: NurbyColors.card,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (sheetContext) => SafeArea(
        child: SizedBox(
          height: MediaQuery.of(sheetContext).size.height * 0.6,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Padding(
                padding: EdgeInsets.fromLTRB(16, 16, 16, 8),
                child: Text('Past runs',
                    style:
                        TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
              ),
              Expanded(
                child: FutureBuilder<List<Map<String, dynamic>>>(
                  future: _fetchRuns(),
                  builder: (context, snap) {
                    if (snap.connectionState != ConnectionState.done) {
                      return const Center(child: CircularProgressIndicator());
                    }
                    if (snap.hasError) {
                      return Center(
                        child: Text(apiErrorMessage(snap.error!),
                            style: const TextStyle(
                                color: NurbyColors.mutedForeground)),
                      );
                    }
                    final runs = snap.data ?? const [];
                    if (runs.isEmpty) {
                      return const Center(
                        child: Text('No runs yet',
                            style: TextStyle(
                                color: NurbyColors.mutedForeground)),
                      );
                    }
                    return ListView.separated(
                      itemCount: runs.length,
                      separatorBuilder: (_, __) => const Divider(height: 1),
                      itemBuilder: (context, i) {
                        final run = runs[i];
                        final created =
                            DateTime.tryParse(run['created_at'] as String? ?? '')
                                ?.toLocal();
                        final status = run['status'] as String? ?? '';
                        return ListTile(
                          title: Text(
                            run['question'] as String? ?? '(no question)',
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(fontSize: 14),
                          ),
                          subtitle: Padding(
                            padding: const EdgeInsets.only(top: 3),
                            child: Row(
                              children: [
                                Text(
                                  status.toUpperCase(),
                                  style: monoStyle.copyWith(
                                    fontSize: 10.5,
                                    color: status == 'completed'
                                        ? NurbyColors.accent
                                        : status == 'failed'
                                            ? NurbyColors.danger
                                            : NurbyColors.mutedForeground,
                                  ),
                                ),
                                const SizedBox(width: 10),
                                if (created != null)
                                  Text(
                                    DateFormat('MMM d · HH:mm')
                                        .format(created),
                                    style: monoStyle.copyWith(fontSize: 10.5),
                                  ),
                              ],
                            ),
                          ),
                          onTap: () {
                            Navigator.of(sheetContext).pop();
                            _loadRun(run['id'] as String? ?? '');
                          },
                        );
                      },
                    );
                  },
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _loadRun(String id) async {
    if (id.isEmpty) return;
    try {
      final j = await ref.read(apiClientProvider).getJson('/api/agent/runs/$id')
          as Map;
      if (!mounted) return;
      final question = j['question'] as String? ?? '';
      final answer = j['answer'] as String? ??
          j['final_answer'] as String? ??
          j['result'] as String? ??
          '';
      setState(() {
        if (question.isNotEmpty) {
          _items.add(_ChatItem(_ItemKind.user, question));
        }
        _items.add(_ChatItem(_ItemKind.assistant,
            answer.trim().isEmpty ? '(no answer recorded)' : answer));
      });
      _scrollToBottom();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
    }
  }

  // ---- UI ----

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Ask Nurby'),
        actions: [
          IconButton(
            icon: const Icon(Icons.history),
            tooltip: 'Past runs',
            onPressed: _showHistory,
          ),
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: _items.isEmpty
                ? const _EmptyChat()
                : ListView.builder(
                    controller: _scroll,
                    padding: const EdgeInsets.fromLTRB(12, 12, 12, 8),
                    itemCount: _items.length,
                    itemBuilder: (context, i) => _ChatItemView(_items[i]),
                  ),
          ),
          _composerBar(),
        ],
      ),
    );
  }

  Widget _composerBar() {
    return Container(
      decoration: const BoxDecoration(
        color: NurbyColors.card,
        border: Border(top: BorderSide(color: NurbyColors.border)),
      ),
      padding: const EdgeInsets.fromLTRB(12, 8, 8, 8),
      child: SafeArea(
        top: false,
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            Expanded(
              child: TextField(
                controller: _composer,
                enabled: !_running,
                minLines: 1,
                maxLines: 4,
                textInputAction: TextInputAction.send,
                onSubmitted: (_) => _send(),
                decoration: InputDecoration(
                  hintText:
                      _running ? 'Nurby is thinking…' : 'Ask about your cameras',
                  fillColor: NurbyColors.background,
                  isDense: true,
                  contentPadding: const EdgeInsets.symmetric(
                      horizontal: 14, vertical: 10),
                ),
              ),
            ),
            const SizedBox(width: 6),
            IconButton(
              icon: _running
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(
                          strokeWidth: 2, color: NurbyColors.accent),
                    )
                  : const Icon(Icons.send, color: NurbyColors.accent),
              onPressed: _running ? null : _send,
            ),
          ],
        ),
      ),
    );
  }
}

class _ChatItemView extends StatelessWidget {
  const _ChatItemView(this.item);
  final _ChatItem item;

  @override
  Widget build(BuildContext context) {
    switch (item.kind) {
      case _ItemKind.tool:
        return Padding(
          padding: const EdgeInsets.fromLTRB(6, 2, 6, 8),
          child: Text('⚙ ${item.text}',
              style: monoStyle.copyWith(fontSize: 11)),
        );
      case _ItemKind.user:
        return _bubble(
          context,
          alignRight: true,
          background: NurbyColors.accent.withValues(alpha: 0.14),
          borderColor: NurbyColors.accent.withValues(alpha: 0.35),
          child: Text(item.text,
              style: const TextStyle(fontSize: 14, height: 1.4)),
        );
      case _ItemKind.error:
        return _bubble(
          context,
          alignRight: false,
          background: NurbyColors.danger.withValues(alpha: 0.10),
          borderColor: NurbyColors.danger.withValues(alpha: 0.5),
          child: Text(item.text,
              style: const TextStyle(
                  fontSize: 13.5, color: NurbyColors.danger, height: 1.4)),
        );
      case _ItemKind.assistant:
        return _bubble(
          context,
          alignRight: false,
          background: NurbyColors.card,
          borderColor: NurbyColors.border,
          child: item.streaming && item.text.isEmpty
              ? const SizedBox(
                  width: 30,
                  height: 16,
                  child: Align(
                    alignment: Alignment.centerLeft,
                    child: SizedBox(
                      width: 14,
                      height: 14,
                      child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: NurbyColors.mutedForeground),
                    ),
                  ),
                )
              : Text(
                  item.streaming ? '${item.text} ▌' : item.text,
                  style: const TextStyle(fontSize: 14, height: 1.45),
                ),
        );
    }
  }

  Widget _bubble(
    BuildContext context, {
    required bool alignRight,
    required Color background,
    required Color borderColor,
    required Widget child,
  }) {
    return Align(
      alignment: alignRight ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 9),
        constraints: BoxConstraints(
          maxWidth: MediaQuery.of(context).size.width * 0.80,
        ),
        decoration: BoxDecoration(
          color: background,
          border: Border.all(color: borderColor),
          borderRadius: BorderRadius.only(
            topLeft: const Radius.circular(14),
            topRight: const Radius.circular(14),
            bottomLeft: Radius.circular(alignRight ? 14 : 4),
            bottomRight: Radius.circular(alignRight ? 4 : 14),
          ),
        ),
        child: child,
      ),
    );
  }
}

class _EmptyChat extends StatelessWidget {
  const _EmptyChat();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.auto_awesome,
                size: 44, color: NurbyColors.mutedForeground),
            const SizedBox(height: 14),
            const Text('Ask Nurby',
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
            const SizedBox(height: 6),
            const Text(
              'The agent can search footage, check cameras\nand summarize what happened.',
              textAlign: TextAlign.center,
              style: TextStyle(
                  color: NurbyColors.mutedForeground, fontSize: 13),
            ),
            const SizedBox(height: 16),
            Text('"Did anyone come to the door today?"',
                style: monoStyle.copyWith(fontSize: 12)),
          ],
        ),
      ),
    );
  }
}
