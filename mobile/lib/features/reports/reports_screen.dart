import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../models/models.dart';

/// Scheduled reports (issue #166): saved Ask questions on a clock.
final reportsProvider = FutureProvider<List<ScheduledReport>>(
    (ref) => ref.watch(reportRepoProvider).list());

/// People, for the optional "about one person" focus.
final _peopleProvider = FutureProvider<List<Person>>((ref) async {
  final j = await ref.watch(apiClientProvider).getJson('/api/persons') as List;
  return j
      .whereType<Map>()
      .map((p) => Person.fromJson(p.cast<String, dynamic>()))
      .toList();
});

const kDays = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
const kDayLabels = {
  'mon': 'Mon', 'tue': 'Tue', 'wed': 'Wed', 'thu': 'Thu',
  'fri': 'Fri', 'sat': 'Sat', 'sun': 'Sun',
};

/// How a report's schedule reads. Pure, for tests.
String scheduleLabel(ScheduledReport r) {
  if (r.everyDay) return 'Every day at ${r.timeLabel}';
  final days = r.days!;
  const weekdays = ['mon', 'tue', 'wed', 'thu', 'fri'];
  const weekend = ['sat', 'sun'];
  if (days.length == 5 && weekdays.every(days.contains)) {
    return 'Weekdays at ${r.timeLabel}';
  }
  if (days.length == 2 && weekend.every(days.contains)) {
    return 'Weekends at ${r.timeLabel}';
  }
  final ordered = kDays.where(days.contains).map((d) => kDayLabels[d]!);
  return '${ordered.join(', ')} at ${r.timeLabel}';
}

/// Where a report goes. Pure, for tests.
List<String> deliveryLabels(Map<String, dynamic> delivery) => [
      // notify defaults to true server-side, so absence means on.
      if (delivery['notify'] != false) 'in app',
      if ((delivery['email'] as String?)?.trim().isNotEmpty ?? false)
        'email',
      if ((delivery['telegram_channel_id']?.toString().trim().isNotEmpty ??
          false))
        'Telegram',
      if ((delivery['webhook'] as String?)?.trim().isNotEmpty ?? false)
        'webhook',
    ];

class ReportsScreen extends ConsumerWidget {
  const ReportsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(reportsProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Reports'),
        actions: [
          IconButton(
            icon: const Icon(Icons.add),
            onPressed: () => _openEditor(context, null),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(reportsProvider),
        child: async.when(
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
                onPressed: () => ref.invalidate(reportsProvider),
                child: const Text('Retry'),
              ),
            ),
          ]),
          data: (items) => items.isEmpty
              ? ListView(children: [
                  const SizedBox(height: 96),
                  const Icon(Icons.schedule_send_outlined,
                      size: 40, color: NurbyColors.mutedForeground),
                  const SizedBox(height: 12),
                  const Center(
                      child: Text('No reports yet',
                          style: TextStyle(fontWeight: FontWeight.w600))),
                  const SizedBox(height: 6),
                  const Padding(
                    padding: EdgeInsets.symmetric(horizontal: 40),
                    child: Text(
                      'A report is a question Nurby answers on a schedule. '
                      '"What did Sam do today", every evening at seven.',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                          fontSize: 12, color: NurbyColors.mutedForeground),
                    ),
                  ),
                  const SizedBox(height: 16),
                  Center(
                    child: FilledButton(
                      onPressed: () => _openEditor(context, null),
                      child: const Text('Create one'),
                    ),
                  ),
                ])
              : ListView.builder(
                  padding: const EdgeInsets.only(bottom: 24),
                  itemCount: items.length,
                  itemBuilder: (_, i) => _ReportTile(
                    report: items[i],
                    onEdit: () => _openEditor(context, items[i]),
                  ),
                ),
        ),
      ),
    );
  }

  void _openEditor(BuildContext context, ScheduledReport? existing) {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      backgroundColor: NurbyColors.cardElevated,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => ReportEditor(existing: existing),
    );
  }
}

class _ReportTile extends ConsumerStatefulWidget {
  const _ReportTile({required this.report, required this.onEdit});

  final ScheduledReport report;
  final VoidCallback onEdit;

  @override
  ConsumerState<_ReportTile> createState() => _ReportTileState();
}

class _ReportTileState extends ConsumerState<_ReportTile> {
  bool _running = false;
  bool _expanded = false;

  Future<void> _run() async {
    setState(() => _running = true);
    try {
      await ref.read(reportRepoProvider).run(widget.report.id);
      ref.invalidate(reportsProvider);
      if (mounted) setState(() => _expanded = true);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    } finally {
      if (mounted) setState(() => _running = false);
    }
  }

  Future<void> _toggle(bool on) async {
    try {
      await ref
          .read(reportRepoProvider)
          .update(widget.report.id, {'enabled': on});
      ref.invalidate(reportsProvider);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final r = widget.report;
    final hasOutput = r.lastOutput?.trim().isNotEmpty ?? false;
    final failed = r.lastStatus == 'failed';

    return Card(
      margin: const EdgeInsets.fromLTRB(12, 6, 12, 0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ListTile(
            title: Text(r.name,
                style: TextStyle(
                    fontWeight: FontWeight.w600,
                    fontSize: 14,
                    color: r.enabled ? null : NurbyColors.mutedForeground)),
            subtitle: Text(
              [
                scheduleLabel(r),
                deliveryLabels(r.delivery).join(', '),
              ].join(' · '),
              style: _sub,
            ),
            trailing: Switch(
              value: r.enabled,
              activeColor: NurbyColors.accent,
              onChanged: _toggle,
            ),
            onTap: widget.onEdit,
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 10),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('"${r.prompt}"',
                    maxLines: _expanded ? null : 2,
                    overflow: _expanded ? null : TextOverflow.ellipsis,
                    style: const TextStyle(
                        fontSize: 12, fontStyle: FontStyle.italic)),
                const SizedBox(height: 8),
                Row(
                  children: [
                    OutlinedButton.icon(
                      onPressed: _running ? null : _run,
                      icon: _running
                          ? const SizedBox(
                              width: 14,
                              height: 14,
                              child: CircularProgressIndicator(strokeWidth: 2))
                          : const Icon(Icons.play_arrow, size: 16),
                      label: Text(_running ? 'Running' : 'Run now'),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        r.lastRunAt == null
                            ? 'Never run'
                            : '${failed ? 'Failed' : 'Ran'} '
                                '${DateFormat('MMM d, HH:mm').format(r.lastRunAt!.toLocal())}',
                        style: TextStyle(
                            fontSize: 11,
                            color: failed
                                ? NurbyColors.danger
                                : NurbyColors.mutedForeground),
                      ),
                    ),
                    if (hasOutput)
                      IconButton(
                        icon: Icon(
                            _expanded ? Icons.expand_less : Icons.expand_more,
                            size: 18),
                        onPressed: () =>
                            setState(() => _expanded = !_expanded),
                      ),
                  ],
                ),
                if (hasOutput && _expanded) ...[
                  const SizedBox(height: 8),
                  // The last answer, kept on the tile. This is how someone
                  // decides whether a question is worth keeping on a
                  // schedule: by reading what it actually produced.
                  Container(
                    padding: const EdgeInsets.all(10),
                    decoration: BoxDecoration(
                      color: NurbyColors.background,
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: NurbyColors.border),
                    ),
                    child: Text(r.lastOutput!.trim(),
                        style: const TextStyle(fontSize: 12)),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class ReportEditor extends ConsumerStatefulWidget {
  const ReportEditor({super.key, this.existing});

  final ScheduledReport? existing;

  @override
  ConsumerState<ReportEditor> createState() => _ReportEditorState();
}

class _ReportEditorState extends ConsumerState<ReportEditor> {
  late final _name = TextEditingController(text: widget.existing?.name ?? '');
  late final _prompt =
      TextEditingController(text: widget.existing?.prompt ?? '');
  late final _email = TextEditingController(
      text: widget.existing?.delivery['email'] as String? ?? '');
  late final _telegram = TextEditingController(
      text: widget.existing?.delivery['telegram_channel_id']?.toString() ?? '');
  late TimeOfDay _time = TimeOfDay(
      hour: widget.existing?.hour ?? 19, minute: widget.existing?.minute ?? 0);
  late final Set<String> _days = {...?widget.existing?.days};
  late String? _personId = widget.existing?.personId;
  late bool _notify = widget.existing?.delivery['notify'] != false;
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _name.dispose();
    _prompt.dispose();
    _email.dispose();
    _telegram.dispose();
    super.dispose();
  }

  Map<String, dynamic> get _body => {
        'name': _name.text.trim(),
        'prompt': _prompt.text.trim(),
        'person_id': _personId,
        'hour': _time.hour,
        'minute': _time.minute,
        // Empty means every day. Sending null rather than [] matches
        // what the server stores, so the tile reads "Every day" instead
        // of an empty list after a round trip.
        'days': _days.isEmpty ? null : kDays.where(_days.contains).toList(),
        'delivery': {
          'notify': _notify,
          if (_email.text.trim().isNotEmpty) 'email': _email.text.trim(),
          if (_telegram.text.trim().isNotEmpty)
            'telegram_channel_id': _telegram.text.trim(),
        },
      };

  Future<void> _save() async {
    if (_name.text.trim().isEmpty || _prompt.text.trim().isEmpty) {
      setState(() => _error = 'A report needs a name and a question.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final repo = ref.read(reportRepoProvider);
      if (widget.existing == null) {
        await repo.create(_body);
      } else {
        await repo.update(widget.existing!.id, _body);
      }
      ref.invalidate(reportsProvider);
      if (mounted) Navigator.pop(context);
    } catch (e) {
      if (mounted) setState(() => _error = apiErrorMessage(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _delete() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: NurbyColors.cardElevated,
        title: const Text('Delete report?'),
        content: Text('"${widget.existing!.name}" will stop running.'),
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
    if (confirmed != true || !mounted) return;
    try {
      await ref.read(reportRepoProvider).remove(widget.existing!.id);
      ref.invalidate(reportsProvider);
      if (mounted) Navigator.pop(context);
    } catch (e) {
      if (mounted) setState(() => _error = apiErrorMessage(e));
    }
  }

  @override
  Widget build(BuildContext context) {
    final people = ref.watch(_peopleProvider).value ?? const <Person>[];

    return Padding(
      padding: EdgeInsets.only(
        left: 20,
        right: 20,
        top: 20,
        bottom: MediaQuery.of(context).viewInsets.bottom + 24,
      ),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(widget.existing == null ? 'New report' : 'Edit report',
                style: const TextStyle(
                    fontSize: 17, fontWeight: FontWeight.w700)),
            const SizedBox(height: 16),
            TextField(
              controller: _name,
              maxLength: 255,
              decoration: const InputDecoration(
                  labelText: 'Name', counterText: '', border: OutlineInputBorder()),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _prompt,
              maxLines: 3,
              decoration: const InputDecoration(
                labelText: 'The question',
                hintText: 'What did Sam do today?',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String?>(
              value: _personId,
              dropdownColor: NurbyColors.cardElevated,
              decoration: const InputDecoration(
                  labelText: 'About', border: OutlineInputBorder()),
              items: [
                const DropdownMenuItem(
                    value: null, child: Text('The whole household')),
                for (final p in people)
                  DropdownMenuItem(value: p.id, child: Text(p.displayName)),
              ],
              onChanged: (v) => setState(() => _personId = v),
            ),
            const SizedBox(height: 12),
            ListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Time'),
              subtitle: Text(_time.format(context), style: _sub),
              trailing: const Icon(Icons.schedule, size: 18),
              onTap: () async {
                final t = await showTimePicker(
                    context: context, initialTime: _time);
                if (t != null) setState(() => _time = t);
              },
            ),
            const Text('Days', style: TextStyle(fontSize: 13)),
            const SizedBox(height: 4),
            Wrap(
              spacing: 6,
              children: [
                for (final d in kDays)
                  FilterChip(
                    label: Text(kDayLabels[d]!,
                        style: const TextStyle(fontSize: 12)),
                    selected: _days.contains(d),
                    onSelected: (on) => setState(() {
                      if (on) {
                        _days.add(d);
                      } else {
                        _days.remove(d);
                      }
                    }),
                  ),
              ],
            ),
            Text(
              _days.isEmpty ? 'Every day' : '${_days.length} of 7 days',
              style: _sub,
            ),
            const SizedBox(height: 12),
            const Text('Send it', style: TextStyle(fontSize: 13)),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('In the app'),
              value: _notify,
              activeColor: NurbyColors.accent,
              onChanged: (v) => setState(() => _notify = v),
            ),
            TextField(
              controller: _email,
              keyboardType: TextInputType.emailAddress,
              autocorrect: false,
              decoration: const InputDecoration(
                  labelText: 'Email (optional)',
                  isDense: true,
                  border: OutlineInputBorder()),
            ),
            const SizedBox(height: 8),
            TextField(
              controller: _telegram,
              autocorrect: false,
              decoration: const InputDecoration(
                  labelText: 'Telegram chat id (optional)',
                  isDense: true,
                  border: OutlineInputBorder()),
            ),
            if (_error != null) ...[
              const SizedBox(height: 12),
              Text(_error!,
                  style: const TextStyle(
                      color: NurbyColors.danger, fontSize: 13)),
            ],
            const SizedBox(height: 16),
            Row(
              children: [
                if (widget.existing != null)
                  TextButton(
                    onPressed: _busy ? null : _delete,
                    child: const Text('Delete',
                        style: TextStyle(color: NurbyColors.danger)),
                  ),
                const Spacer(),
                TextButton(
                    onPressed: () => Navigator.pop(context),
                    child: const Text('Cancel')),
                const SizedBox(width: 8),
                FilledButton(
                  onPressed: _busy ? null : _save,
                  child: Text(widget.existing == null ? 'Create' : 'Save'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

const _sub = TextStyle(color: NurbyColors.mutedForeground, fontSize: 12);
