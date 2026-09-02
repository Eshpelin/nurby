import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';

/// The four things around Ask that mobile lacked (issue #170): mentions,
/// a model picker, today's usage, and what a run actually looked at.

// ---------------------------------------------------------------------
// Mentions
// ---------------------------------------------------------------------

/// One flat list of everything a question can @-mention. Cached for the
/// session and filtered on the phone, which is what the web does too.
final mentionsProvider = FutureProvider<List<Mention>>((ref) async {
  final j = await ref.watch(apiClientProvider).getJson('/api/mentions') as List;
  return j
      .whereType<Map>()
      .map((m) => Mention.fromJson(m.cast<String, dynamic>()))
      .toList();
});

class Mention {
  const Mention({required this.kind, required this.id, required this.name, this.hint});

  factory Mention.fromJson(Map<String, dynamic> j) => Mention(
        kind: j['kind'] as String,
        id: j['id'] as String,
        name: j['name'] as String,
        hint: j['hint'] as String?,
      );

  final String kind; // person | camera | telegram_channel | device
  final String id;
  final String name;
  final String? hint;

  /// The body shape the API expects in `mentions`.
  Map<String, dynamic> toRef() => {'kind': kind, 'id': id, 'name': name};
}

/// The `@` token the cursor is currently inside, or null.
///
/// Pure. Looks back from the cursor for an `@` that begins a token,
/// meaning it is at the start or follows whitespace, and returns the
/// text typed after it. Stops at whitespace so a completed mention does
/// not keep the picker open.
String? activeMentionQuery(String text, int cursor) {
  if (cursor < 0 || cursor > text.length) return null;
  final before = text.substring(0, cursor);
  final at = before.lastIndexOf('@');
  if (at < 0) return null;
  if (at > 0 && !_isSpace(before[at - 1])) return null;
  final query = before.substring(at + 1);
  if (query.contains(RegExp(r'\s'))) return null;
  return query;
}

bool _isSpace(String c) => c.trim().isEmpty;

/// Replace the active `@query` with `@Name ` and return the new text and
/// cursor. Pure.
({String text, int cursor}) insertMention(String text, int cursor, String name) {
  final before = text.substring(0, cursor);
  final at = before.lastIndexOf('@');
  final replaced = '${text.substring(0, at)}@$name ';
  return (text: replaced + text.substring(cursor), cursor: replaced.length);
}

/// Which mentions still appear in the text at send time. Someone can
/// pick a mention and then delete it, and the API must not be told
/// about a person the question no longer names.
List<Mention> mentionsStillPresent(String text, Iterable<Mention> picked) =>
    picked.where((m) => text.contains('@${m.name}')).toList();

/// Rank candidates: prefix matches first, then substring, both
/// case-insensitive, capped so the strip stays one row.
List<Mention> matchMentions(List<Mention> all, String query, {int limit = 6}) {
  final q = query.toLowerCase();
  final prefix = <Mention>[];
  final inner = <Mention>[];
  for (final m in all) {
    final n = m.name.toLowerCase();
    if (q.isEmpty || n.startsWith(q)) {
      prefix.add(m);
    } else if (n.contains(q)) {
      inner.add(m);
    }
  }
  return [...prefix, ...inner].take(limit).toList();
}

class MentionStrip extends StatelessWidget {
  const MentionStrip({super.key, required this.candidates, required this.onPick});

  final List<Mention> candidates;
  final ValueChanged<Mention> onPick;

  @override
  Widget build(BuildContext context) {
    if (candidates.isEmpty) return const SizedBox.shrink();
    return Container(
      color: NurbyColors.card,
      padding: const EdgeInsets.fromLTRB(12, 6, 12, 0),
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Row(
          children: [
            for (final m in candidates)
              Padding(
                padding: const EdgeInsets.only(right: 6),
                child: ActionChip(
                  avatar: Icon(_icon(m.kind), size: 14),
                  label: Text(m.name, style: const TextStyle(fontSize: 12)),
                  onPressed: () => onPick(m),
                ),
              ),
          ],
        ),
      ),
    );
  }

  static IconData _icon(String kind) => switch (kind) {
        'person' => Icons.person_outline,
        'camera' => Icons.videocam_outlined,
        'telegram_channel' => Icons.send_outlined,
        _ => Icons.devices_other,
      };
}

// ---------------------------------------------------------------------
// Model picker
// ---------------------------------------------------------------------

final agentProvidersProvider =
    FutureProvider<List<Map<String, dynamic>>>((ref) async {
  final j =
      await ref.watch(apiClientProvider).getJson('/api/agent/providers') as List;
  return j.whereType<Map>().map((p) => p.cast<String, dynamic>()).toList();
});

/// The chosen provider and model, remembered across launches the way the
/// web remembers it in localStorage. Null means the server default.
class ModelChoice {
  const ModelChoice({required this.providerId, required this.model});
  final String providerId;
  final String model;
}

const _kModelPrefKey = 'ask_model_choice';

Future<ModelChoice?> loadModelChoice() async {
  try {
    final p = await SharedPreferences.getInstance();
    final raw = p.getString(_kModelPrefKey);
    if (raw == null || !raw.contains('|')) return null;
    final i = raw.indexOf('|');
    return ModelChoice(
        providerId: raw.substring(0, i), model: raw.substring(i + 1));
  } catch (_) {
    return null;
  }
}

Future<void> saveModelChoice(ModelChoice? c) async {
  try {
    final p = await SharedPreferences.getInstance();
    if (c == null) {
      await p.remove(_kModelPrefKey);
    } else {
      await p.setString(_kModelPrefKey, '${c.providerId}|${c.model}');
    }
  } catch (_) {}
}

class ModelPickerSheet extends ConsumerWidget {
  const ModelPickerSheet({super.key, required this.current});

  final ModelChoice? current;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(agentProvidersProvider);

    return SafeArea(
      child: async.when(
        loading: () => const Padding(
            padding: EdgeInsets.all(24), child: LinearProgressIndicator()),
        error: (e, _) => Padding(
            padding: const EdgeInsets.all(24),
            child: Text(apiErrorMessage(e), style: _sub)),
        data: (providers) => ListView(
          shrinkWrap: true,
          children: [
            const Padding(
              padding: EdgeInsets.fromLTRB(16, 16, 16, 4),
              child: Text('Which model answers',
                  style: TextStyle(fontWeight: FontWeight.w600)),
            ),
            ListTile(
              leading: Icon(Icons.auto_awesome,
                  color: current == null
                      ? NurbyColors.accent
                      : NurbyColors.mutedForeground),
              title: const Text('Server default'),
              onTap: () => Navigator.pop(context, const _Clear()),
            ),
            for (final p in providers) ...[
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 12, 16, 2),
                child: Text('${p['label']}',
                    style: const TextStyle(
                        fontSize: 12,
                        color: NurbyColors.mutedForeground,
                        fontWeight: FontWeight.w600)),
              ),
              for (final m in (p['models'] as List? ?? const []).whereType<Map>())
                ListTile(
                  dense: true,
                  leading: Icon(
                    Icons.check,
                    size: 18,
                    color: current?.providerId == p['provider_id'] &&
                            current?.model == m['name']
                        ? NurbyColors.accent
                        : Colors.transparent,
                  ),
                  title: Text('${m['label'] ?? m['name']}',
                      style: const TextStyle(fontSize: 13)),
                  // A model that cannot call tools cannot answer
                  // questions about cameras. It is listed so its
                  // absence is not a mystery, and it says why.
                  subtitle: m['supports_tools'] == false
                      ? const Text('Cannot use tools, so cannot look at '
                          'your cameras', style: _sub)
                      : (m['recommended'] == true
                          ? const Text('Recommended', style: _sub)
                          : null),
                  enabled: m['supports_tools'] != false,
                  onTap: () => Navigator.pop(
                      context,
                      ModelChoice(
                          providerId: p['provider_id'] as String,
                          model: m['name'] as String)),
                ),
            ],
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
  }
}

/// Sentinel returned when the sheet picks "server default", so a
/// dismissed sheet (null) is distinguishable from an explicit clear.
class _Clear {
  const _Clear();
}

/// Show the picker and return the new choice, or the old one on dismiss.
Future<ModelChoice?> pickModel(BuildContext context, ModelChoice? current) async {
  final r = await showModalBottomSheet<Object>(
    context: context,
    backgroundColor: NurbyColors.cardElevated,
    builder: (_) => ModelPickerSheet(current: current),
  );
  if (r == null) return current;
  if (r is _Clear) return null;
  return r as ModelChoice;
}

// ---------------------------------------------------------------------
// Usage
// ---------------------------------------------------------------------

final usageTodayProvider = FutureProvider<Map<String, dynamic>>((ref) async =>
    (await ref.watch(apiClientProvider).getJson('/api/agent/usage/today') as Map)
        .cast<String, dynamic>());

class UsageChip extends ConsumerWidget {
  const UsageChip({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final u = ref.watch(usageTodayProvider).value;
    if (u == null) return const SizedBox.shrink();
    final pct = (u['percent_used'] as num?)?.toInt();
    if (pct == null) return const SizedBox.shrink();
    final warn = u['warn'] == true;

    return Tooltip(
      message: usageSummary(u),
      child: Padding(
        padding: const EdgeInsets.only(right: 4),
        child: Center(
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
            decoration: BoxDecoration(
              color: (warn ? NurbyColors.warning : NurbyColors.accent)
                  .withValues(alpha: 0.15),
              borderRadius: BorderRadius.circular(10),
            ),
            child: Text('$pct% today',
                style: TextStyle(
                    fontSize: 11,
                    color: warn ? NurbyColors.warning : NurbyColors.accent)),
          ),
        ),
      ),
    );
  }
}

/// One sentence about today's budget. Pure.
String usageSummary(Map<String, dynamic> u) {
  final usedT = (u['used_tokens'] as num?)?.toInt();
  final budgetT = (u['token_budget'] as num?)?.toInt();
  final usedC = (u['used_cost_cents'] as num?)?.toDouble();
  final budgetC = (u['cost_budget_cents'] as num?)?.toDouble();
  final parts = <String>[];
  if (usedT != null && budgetT != null && budgetT > 0) {
    parts.add('${_k(usedT)} of ${_k(budgetT)} tokens');
  }
  if (usedC != null && budgetC != null && budgetC > 0) {
    parts.add('\$${(usedC / 100).toStringAsFixed(2)} of '
        '\$${(budgetC / 100).toStringAsFixed(2)}');
  }
  return parts.isEmpty ? 'No budget set' : parts.join(', ');
}

/// 12500 reads as 12.5k, 100000 as 100k. One decimal until the number
/// is big enough that it stops carrying information.
String _k(int n) {
  if (n < 1000) return '$n';
  final k = n / 1000;
  return '${k.toStringAsFixed(k >= 100 ? 0 : 1)}k'.replaceAll('.0k', 'k');
}

// ---------------------------------------------------------------------
// Run inspection
// ---------------------------------------------------------------------

/// What a run actually looked at: each VLM call, with its question,
/// answer and cost. Shown from history so an answer can be checked
/// against what the model was shown rather than taken on trust.
class RunInspection extends StatelessWidget {
  const RunInspection({super.key, required this.run});

  final Map<String, dynamic> run;

  @override
  Widget build(BuildContext context) {
    final vlm = (run['vlm_calls'] as List? ?? const [])
        .whereType<Map>()
        .map((v) => v.cast<String, dynamic>())
        .toList();
    final tools = (run['tool_calls'] as List? ?? const []).length;
    final cost = (run['cost_cents'] as num?)?.toDouble();
    final tin = (run['tokens_in'] as num?)?.toInt();
    final tout = (run['tokens_out'] as num?)?.toInt();
    final ms = (run['latency_ms'] as num?)?.toInt();

    return SafeArea(
      child: ListView(
        padding: const EdgeInsets.all(16),
        shrinkWrap: true,
        children: [
          const Text('What this run did',
              style: TextStyle(fontWeight: FontWeight.w600)),
          const SizedBox(height: 6),
          Text(
            [
              if (run['model'] != null) '${run['model']}',
              '$tools ${tools == 1 ? 'tool call' : 'tool calls'}',
              '${vlm.length} ${vlm.length == 1 ? 'look' : 'looks'} at footage',
              if (tin != null && tout != null) '${_k(tin)} in, ${_k(tout)} out',
              if (cost != null) '\$${(cost / 100).toStringAsFixed(3)}',
              if (ms != null) '${(ms / 1000).toStringAsFixed(1)}s',
            ].join(' · '),
            style: _sub,
          ),
          if (run['error_message'] != null) ...[
            const SizedBox(height: 8),
            Text('${run['error_message']}',
                style: const TextStyle(fontSize: 12, color: NurbyColors.danger)),
          ],
          if (vlm.isNotEmpty) ...[
            const SizedBox(height: 14),
            const Text('Looks at footage',
                style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
            for (final v in vlm)
              Container(
                margin: const EdgeInsets.only(top: 8),
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  border: Border.all(color: NurbyColors.border),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('${v['question'] ?? ''}',
                        style: const TextStyle(
                            fontSize: 12, fontStyle: FontStyle.italic)),
                    const SizedBox(height: 4),
                    Text('${v['response'] ?? ''}',
                        style: const TextStyle(fontSize: 12)),
                    const SizedBox(height: 4),
                    Text(
                      [
                        if (v['target_kind'] != null) '${v['target_kind']}',
                        if (v['frame_count'] != null)
                          '${v['frame_count']} frames',
                        if (v['cached'] == true) 'cached',
                        if (v['created_at'] != null)
                          DateFormat('HH:mm:ss').format(
                              DateTime.parse('${v['created_at']}').toLocal()),
                      ].join(' · '),
                      style: _sub,
                    ),
                  ],
                ),
              ),
          ],
        ],
      ),
    );
  }
}

const _sub = TextStyle(color: NurbyColors.mutedForeground, fontSize: 12);
