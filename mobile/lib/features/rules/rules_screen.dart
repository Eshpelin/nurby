import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../models/models.dart';

/// Shared so the rule editor can invalidate the list after save.
final rulesProvider =
    FutureProvider<List<Rule>>((ref) => ref.watch(ruleRepoProvider).list());

/// Automation rules: list, enable/disable, snooze, delete.
class RulesScreen extends ConsumerWidget {
  const RulesScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final rulesAsync = ref.watch(rulesProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Rules')),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => context.go('/more/rules/new'),
        icon: const Icon(Icons.add),
        label: const Text('New rule'),
      ),
      body: rulesAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Text(apiErrorMessage(e),
                style: const TextStyle(color: NurbyColors.mutedForeground)),
          ),
        ),
        data: (rules) => RefreshIndicator(
          onRefresh: () => ref.refresh(rulesProvider.future),
          child: rules.isEmpty
              ? ListView(
                  physics: const AlwaysScrollableScrollPhysics(),
                  children: const [
                    Padding(
                      padding: EdgeInsets.only(top: 120),
                      child: Center(
                        child: Text(
                          'No rules yet.\nCreate one to get alerted.',
                          textAlign: TextAlign.center,
                          style: TextStyle(color: NurbyColors.mutedForeground),
                        ),
                      ),
                    ),
                  ],
                )
              : ListView.builder(
                  physics: const AlwaysScrollableScrollPhysics(),
                  padding: const EdgeInsets.fromLTRB(12, 12, 12, 88),
                  itemCount: rules.length,
                  itemBuilder: (context, i) => _RuleRow(rule: rules[i]),
                ),
        ),
      ),
    );
  }
}

class _RuleRow extends ConsumerWidget {
  const _RuleRow({required this.rule});
  final Rule rule;

  /// Plain-language one-liner built from trigger + actions.
  static String summary(Rule rule) {
    final t = rule.triggerPattern;
    String when;
    if (t.containsKey('person_id')) {
      when = 'When a known person appears';
    } else {
      final label = t['label'] as String? ?? 'object';
      final conf = (t['confidence_min'] as num?)?.toDouble();
      when = 'When a $label is detected';
      if (conf != null) when += ' (at least ${(conf * 100).round()}%)';
    }
    final acts = rule.actions.map((a) => switch (a['type']) {
          'telegram' => 'Telegram alert',
          'email' => 'email',
          'device' => 'device trigger',
          _ => a['type']?.toString() ?? 'action',
        });
    if (acts.isEmpty) return when;
    return '$when, ${acts.join(' + ')}';
  }

  void _showError(BuildContext context, Object e) {
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
  }

  Future<void> _toggle(BuildContext context, WidgetRef ref, bool value) async {
    try {
      await ref.read(ruleRepoProvider).update(rule.id, {'enabled': value});
      ref.invalidate(rulesProvider);
    } catch (e) {
      if (context.mounted) _showError(context, e);
    }
  }

  Future<void> _snooze(BuildContext context, WidgetRef ref, int seconds) async {
    try {
      await ref.read(ruleRepoProvider).snooze(rule.id, seconds);
      ref.invalidate(rulesProvider);
    } catch (e) {
      if (context.mounted) _showError(context, e);
    }
  }

  Future<void> _unsnooze(BuildContext context, WidgetRef ref) async {
    try {
      await ref.read(ruleRepoProvider).unsnooze(rule.id);
      ref.invalidate(rulesProvider);
    } catch (e) {
      if (context.mounted) _showError(context, e);
    }
  }

  Future<bool> _confirmDelete(BuildContext context) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: NurbyColors.cardElevated,
        title: const Text('Delete rule?'),
        content: Text('"${rule.name}" will be removed permanently.'),
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
    return confirmed ?? false;
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Dismissible(
      key: ValueKey(rule.id),
      direction: DismissDirection.endToStart,
      confirmDismiss: (_) => _confirmDelete(context),
      onDismissed: (_) async {
        try {
          await ref.read(ruleRepoProvider).remove(rule.id);
        } catch (e) {
          if (context.mounted) _showError(context, e);
        } finally {
          ref.invalidate(rulesProvider);
        }
      },
      background: Container(
        alignment: Alignment.centerRight,
        padding: const EdgeInsets.only(right: 20),
        margin: const EdgeInsets.only(bottom: 8),
        decoration: BoxDecoration(
          color: NurbyColors.danger.withValues(alpha: 0.25),
          borderRadius: BorderRadius.circular(12),
        ),
        child: const Icon(Icons.delete_outline, color: NurbyColors.danger),
      ),
      child: Card(
        margin: const EdgeInsets.only(bottom: 8),
        child: InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: () => context.go('/more/rules/${rule.id}/edit'),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(14, 10, 6, 10),
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(rule.name,
                          style: const TextStyle(
                              fontWeight: FontWeight.w600, fontSize: 15)),
                      const SizedBox(height: 3),
                      Text(
                        summary(rule),
                        style: const TextStyle(
                            color: NurbyColors.mutedForeground, fontSize: 12),
                      ),
                      if (rule.snoozed)
                        Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            const Icon(Icons.snooze,
                                size: 14, color: NurbyColors.warning),
                            const SizedBox(width: 4),
                            Text(
                              'Snoozed until '
                              '${DateFormat('MMM d, HH:mm').format(rule.snoozedUntil!)}',
                              style: monoStyle.copyWith(
                                  color: NurbyColors.warning),
                            ),
                            TextButton(
                              style: TextButton.styleFrom(
                                padding:
                                    const EdgeInsets.symmetric(horizontal: 8),
                                minimumSize: const Size(0, 30),
                                tapTargetSize:
                                    MaterialTapTargetSize.shrinkWrap,
                              ),
                              onPressed: () => _unsnooze(context, ref),
                              child: const Text('Unsnooze',
                                  style: TextStyle(fontSize: 12)),
                            ),
                          ],
                        ),
                    ],
                  ),
                ),
                PopupMenuButton<int>(
                  color: NurbyColors.cardElevated,
                  icon: const Icon(Icons.snooze,
                      size: 20, color: NurbyColors.mutedForeground),
                  tooltip: 'Snooze',
                  onSelected: (seconds) => _snooze(context, ref, seconds),
                  itemBuilder: (_) => const [
                    PopupMenuItem(value: 1800, child: Text('Snooze 30 min')),
                    PopupMenuItem(value: 3600, child: Text('Snooze 1 hour')),
                    PopupMenuItem(value: 28800, child: Text('Snooze 8 hours')),
                  ],
                ),
                Switch(
                  value: rule.enabled,
                  activeColor: NurbyColors.accent,
                  onChanged: (v) => _toggle(context, ref, v),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
