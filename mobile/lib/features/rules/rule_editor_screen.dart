import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../models/models.dart';
import 'rules_screen.dart';

final _labelsProvider = FutureProvider<List<String>>((ref) async {
  final j = await ref
      .watch(apiClientProvider)
      .getJson('/api/detection-models/classes');
  final items = j is List ? j : (j as Map)['classes'] as List? ?? [];
  return items.map((e) => e.toString()).toList();
});

final _channelsProvider =
    FutureProvider<List<Map<String, dynamic>>>((ref) async {
  final j =
      await ref.watch(apiClientProvider).getJson('/api/telegram/channels');
  return (j as List? ?? [])
      .whereType<Map>()
      .map((c) => c.cast<String, dynamic>())
      .toList();
});

final _devicesProvider =
    FutureProvider<List<Map<String, dynamic>>>((ref) async {
  final j =
      await ref.watch(apiClientProvider).getJson('/api/devices/instances');
  return (j as List? ?? [])
      .whereType<Map>()
      .map((d) => d.cast<String, dynamic>())
      .toList();
});

final _personsProvider =
    FutureProvider<List<Person>>((ref) => ref.watch(personRepoProvider).list());

final _ruleProvider = FutureProvider.family<Rule, String>((ref, id) async {
  final rules = await ref.watch(ruleRepoProvider).list();
  return rules.firstWhere((r) => r.id == id,
      orElse: () => throw StateError('Rule not found'));
});

/// Create/edit an automation rule: WHEN / AND / THEN, plus natural-language
/// generation and a live plain-language preview.
class RuleEditorScreen extends ConsumerWidget {
  const RuleEditorScreen({super.key, this.ruleId});

  final String? ruleId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (ruleId == null) return const _RuleEditorBody(rule: null);

    final ruleAsync = ref.watch(_ruleProvider(ruleId!));
    return ruleAsync.when(
      loading: () => Scaffold(
        appBar: AppBar(),
        body: const Center(child: CircularProgressIndicator()),
      ),
      error: (e, _) => Scaffold(
        appBar: AppBar(),
        body: Center(child: Text(apiErrorMessage(e))),
      ),
      data: (rule) => _RuleEditorBody(rule: rule),
    );
  }
}

class _RuleEditorBody extends ConsumerStatefulWidget {
  const _RuleEditorBody({required this.rule});
  final Rule? rule;

  @override
  ConsumerState<_RuleEditorBody> createState() => _RuleEditorBodyState();
}

class _RuleEditorBodyState extends ConsumerState<_RuleEditorBody> {
  final _name = TextEditingController();
  final _prompt = TextEditingController();
  final _message = TextEditingController();
  final _recipients = TextEditingController();

  String? _explanation;
  bool _generating = false;
  bool _saving = false;

  // WHEN
  String _triggerType = 'object'; // object | person
  String? _label;
  double _confidence = 0.8;
  String? _personId;

  // AND
  bool _timeWindow = false;
  TimeOfDay? _after;
  TimeOfDay? _before;
  final Set<String> _cameraIds = {};

  // THEN
  String _actionType = 'telegram'; // telegram | email | device
  String? _channelId;
  String? _deviceId;
  int _cooldown = 0;

  bool _enabled = true;
  // Original maps, kept so unknown keys round-trip on save.
  Map<String, dynamic> _baseTrigger = {};
  Map<String, dynamic> _baseConditions = {};
  List<Map<String, dynamic>> _baseActions = [];

  @override
  void initState() {
    super.initState();
    final rule = widget.rule;
    if (rule != null) {
      _name.text = rule.name;
      _enabled = rule.enabled;
      _applyParts(rule.triggerPattern, rule.conditions, rule.actions,
          rule.cooldownSeconds);
    }
  }

  @override
  void dispose() {
    _name.dispose();
    _prompt.dispose();
    _message.dispose();
    _recipients.dispose();
    super.dispose();
  }

  static TimeOfDay? _parseHhMm(dynamic v) {
    if (v is! String) return null;
    final parts = v.split(':');
    if (parts.length < 2) return null;
    final h = int.tryParse(parts[0]);
    final m = int.tryParse(parts[1]);
    if (h == null || m == null) return null;
    return TimeOfDay(hour: h, minute: m);
  }

  static String _fmtHhMm(TimeOfDay t) =>
      '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

  /// Fill the form fields (and the round-trip base maps) from rule parts.
  void _applyParts(Map<String, dynamic> trigger, Map<String, dynamic> conditions,
      List<Map<String, dynamic>> actions, int? cooldown) {
    _baseTrigger = {..._baseTrigger, ...trigger};
    _baseConditions = {..._baseConditions, ...conditions};
    if (actions.isNotEmpty) _baseActions = actions;

    if (trigger.containsKey('person_id')) {
      _triggerType = 'person';
      _personId = trigger['person_id']?.toString();
    } else {
      _triggerType = 'object';
      if (trigger['label'] != null) _label = trigger['label'].toString();
      final conf = (trigger['confidence_min'] as num?)?.toDouble();
      if (conf != null) _confidence = conf.clamp(0.5, 1.0);
    }

    _after = _parseHhMm(conditions['after']);
    _before = _parseHhMm(conditions['before']);
    _timeWindow = _after != null || _before != null;
    _cameraIds
      ..clear()
      ..addAll((conditions['camera_ids'] as List? ?? [])
          .map((e) => e.toString()));

    if (actions.isNotEmpty) {
      final a = actions.first;
      final type = a['type']?.toString();
      if (type == 'telegram' || type == 'email' || type == 'device') {
        _actionType = type!;
      }
      if (a['channel_id'] != null) _channelId = a['channel_id'].toString();
      if (a['message'] != null) _message.text = a['message'].toString();
      if (a['recipients'] is List) {
        _recipients.text = (a['recipients'] as List).join(', ');
      }
      if (a['device_id'] != null) _deviceId = a['device_id'].toString();
    }

    if (cooldown != null) _cooldown = cooldown;
  }

  // ---- Natural-language generation ----

  Future<void> _generate() async {
    final prompt = _prompt.text.trim();
    if (prompt.isEmpty) return;
    setState(() => _generating = true);
    try {
      final res = await ref.read(ruleRepoProvider).generate(prompt);
      final rule = (res['rule'] as Map?)?.cast<String, dynamic>() ?? {};
      setState(() {
        _explanation = res['explanation'] as String?;
        if ((rule['name'] as String?)?.isNotEmpty == true) {
          _name.text = rule['name'] as String;
        }
        _applyParts(
          (rule['trigger_pattern'] as Map?)?.cast<String, dynamic>() ?? {},
          (rule['conditions'] as Map?)?.cast<String, dynamic>() ?? {},
          (rule['actions'] as List?)
                  ?.whereType<Map>()
                  .map((a) => a.cast<String, dynamic>())
                  .toList() ??
              [],
          rule['cooldown_seconds'] as int?,
        );
      });
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    } finally {
      if (mounted) setState(() => _generating = false);
    }
  }

  // ---- Save ----

  Map<String, dynamic>? _buildBody() {
    final name = _name.text.trim();
    if (name.isEmpty) return _invalid('Give the rule a name.');

    final trigger = Map<String, dynamic>.from(_baseTrigger)
      ..remove('label')
      ..remove('confidence_min')
      ..remove('person_id');
    if (_triggerType == 'person') {
      if (_personId == null) return _invalid('Pick a person for the trigger.');
      trigger['person_id'] = _personId;
    } else {
      if (_label == null) return _invalid('Pick an object label.');
      trigger['label'] = _label;
      trigger['confidence_min'] =
          double.parse(_confidence.toStringAsFixed(2));
    }

    final conditions = Map<String, dynamic>.from(_baseConditions)
      ..remove('after')
      ..remove('before')
      ..remove('camera_ids');
    if (_timeWindow) {
      if (_after != null) conditions['after'] = _fmtHhMm(_after!);
      if (_before != null) conditions['before'] = _fmtHhMm(_before!);
    }
    if (_cameraIds.isNotEmpty) conditions['camera_ids'] = _cameraIds.toList();

    // Keep unknown keys only when the action type is unchanged.
    final action = (_baseActions.isNotEmpty &&
            _baseActions.first['type'] == _actionType)
        ? Map<String, dynamic>.from(_baseActions.first)
        : <String, dynamic>{};
    action['type'] = _actionType;
    switch (_actionType) {
      case 'telegram':
        if (_channelId == null) {
          return _invalid('Pick a Telegram channel.');
        }
        final channels = ref.read(_channelsProvider).value ?? [];
        final match = channels
            .where((c) => c['id'].toString() == _channelId)
            .toList();
        action['channel_id'] =
            match.isNotEmpty ? match.first['id'] : _channelId;
        action['message'] = _message.text.trim();
      case 'email':
        final recipients = _recipients.text
            .split(',')
            .map((s) => s.trim())
            .where((s) => s.isNotEmpty)
            .toList();
        if (recipients.isEmpty) {
          return _invalid('Enter at least one email recipient.');
        }
        action['recipients'] = recipients;
      case 'device':
        if (_deviceId == null) return _invalid('Pick a device.');
        action['device_id'] = _deviceId;
    }

    return {
      'name': name,
      'enabled': _enabled,
      'trigger_pattern': trigger,
      'conditions': conditions,
      'actions': [action, ..._baseActions.skip(1)],
      'cooldown_seconds': _cooldown,
    };
  }

  Map<String, dynamic>? _invalid(String message) {
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
    return null;
  }

  Future<void> _save() async {
    final body = _buildBody();
    if (body == null) return;
    setState(() => _saving = true);
    try {
      final repo = ref.read(ruleRepoProvider);
      if (widget.rule == null) {
        await repo.create(body);
      } else {
        await repo.update(widget.rule!.id, body);
        ref.invalidate(_ruleProvider(widget.rule!.id));
      }
      ref.invalidate(rulesProvider);
      if (mounted) context.pop();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  // ---- Preview ----

  String _cooldownPhrase() => switch (_cooldown) {
        0 => '',
        60 => ' At most once every 1 min.',
        300 => ' At most once every 5 min.',
        900 => ' At most once every 15 min.',
        3600 => ' At most once every hour.',
        _ => ' At most once every $_cooldown s.',
      };

  String _previewText() {
    final cameras = ref.watch(camerasProvider).value ?? [];
    final persons = ref.watch(_personsProvider).value ?? [];

    String subject;
    if (_triggerType == 'person') {
      final person =
          persons.where((p) => p.id == _personId).toList();
      subject = person.isNotEmpty ? person.first.displayName : 'a known person';
    } else {
      subject = _label == null ? 'an object' : 'a $_label';
    }

    var where = '';
    if (_cameraIds.isNotEmpty) {
      final names = cameras
          .where((c) => _cameraIds.contains(c.id))
          .map((c) => c.name)
          .toList();
      if (names.isNotEmpty) where = ' on ${names.join(', ')}';
    }

    var when = '';
    if (_timeWindow && _after != null && _before != null) {
      when = ' between ${_fmtHhMm(_after!)} and ${_fmtHhMm(_before!)}';
    } else if (_timeWindow && _after != null) {
      when = ' after ${_fmtHhMm(_after!)}';
    } else if (_timeWindow && _before != null) {
      when = ' before ${_fmtHhMm(_before!)}';
    }

    final then = switch (_actionType) {
      'telegram' => 'send a Telegram alert',
      'email' => 'send an email',
      'device' => 'trigger a device',
      _ => 'run an action',
    };

    return 'If $subject appears$where$when, $then.${_cooldownPhrase()}';
  }

  // ---- UI ----

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.rule == null ? 'New rule' : 'Edit rule'),
        actions: [
          if (_saving)
            const Padding(
              padding: EdgeInsets.only(right: 16),
              child: Center(
                child: SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(strokeWidth: 2)),
              ),
            )
          else
            TextButton(
              onPressed: _save,
              child: const Text('Save',
                  style: TextStyle(
                      color: NurbyColors.accent, fontWeight: FontWeight.w600)),
            ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          _describeCard(),
          const SizedBox(height: 16),
          TextField(
            controller: _name,
            decoration: const InputDecoration(labelText: 'Rule name'),
          ),
          _sectionLabel('WHEN'),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  SegmentedButton<String>(
                    segments: const [
                      ButtonSegment(
                          value: 'object', label: Text('Object detected')),
                      ButtonSegment(
                          value: 'person', label: Text('Known person')),
                    ],
                    selected: {_triggerType},
                    onSelectionChanged: (s) =>
                        setState(() => _triggerType = s.first),
                  ),
                  const SizedBox(height: 12),
                  if (_triggerType == 'object')
                    ..._objectTriggerFields()
                  else
                    _personTriggerField(),
                ],
              ),
            ),
          ),
          _sectionLabel('AND'),
          Card(
            child: Column(
              children: [
                SwitchListTile(
                  title: const Text('Time window'),
                  subtitle: const Text('Only trigger during these hours',
                      style: TextStyle(
                          color: NurbyColors.mutedForeground, fontSize: 12)),
                  value: _timeWindow,
                  activeColor: NurbyColors.accent,
                  onChanged: (v) => setState(() => _timeWindow = v),
                ),
                if (_timeWindow)
                  Row(children: [
                    Expanded(child: _timeTile('After', _after,
                        (t) => setState(() => _after = t))),
                    Expanded(child: _timeTile('Before', _before,
                        (t) => setState(() => _before = t))),
                  ]),
                const Divider(height: 1),
                Padding(
                  padding: const EdgeInsets.all(12),
                  child: _cameraPicker(),
                ),
              ],
            ),
          ),
          _sectionLabel('THEN'),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  DropdownButtonFormField<String>(
                    value: _actionType,
                    decoration: const InputDecoration(labelText: 'Action'),
                    dropdownColor: NurbyColors.cardElevated,
                    items: const [
                      DropdownMenuItem(
                          value: 'telegram', child: Text('Telegram')),
                      DropdownMenuItem(value: 'email', child: Text('Email')),
                      DropdownMenuItem(value: 'device', child: Text('Device')),
                    ],
                    onChanged: (v) =>
                        setState(() => _actionType = v ?? 'telegram'),
                  ),
                  const SizedBox(height: 12),
                  ..._actionFields(),
                  const SizedBox(height: 12),
                  DropdownButtonFormField<int>(
                    value: const [0, 60, 300, 900, 3600].contains(_cooldown)
                        ? _cooldown
                        : 0,
                    decoration: const InputDecoration(labelText: 'Cooldown'),
                    dropdownColor: NurbyColors.cardElevated,
                    items: const [
                      DropdownMenuItem(value: 0, child: Text('No cooldown')),
                      DropdownMenuItem(value: 60, child: Text('1 minute')),
                      DropdownMenuItem(value: 300, child: Text('5 minutes')),
                      DropdownMenuItem(value: 900, child: Text('15 minutes')),
                      DropdownMenuItem(value: 3600, child: Text('1 hour')),
                    ],
                    onChanged: (v) => setState(() => _cooldown = v ?? 0),
                  ),
                ],
              ),
            ),
          ),
          _sectionLabel('PREVIEW'),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Text(
                _previewText(),
                style: const TextStyle(
                    color: NurbyColors.foreground, fontSize: 14, height: 1.5),
              ),
            ),
          ),
          const SizedBox(height: 32),
        ],
      ),
    );
  }

  Widget _describeCard() {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Describe it instead',
                style: TextStyle(fontWeight: FontWeight.w600, fontSize: 15)),
            const SizedBox(height: 4),
            const Text(
              'Write what you want in plain language and let Nurby build the rule.',
              style:
                  TextStyle(color: NurbyColors.mutedForeground, fontSize: 12),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: _prompt,
              maxLines: 2,
              minLines: 1,
              decoration: const InputDecoration(
                  hintText: 'e.g. Alert me on Telegram when someone is at the '
                      'front door after 22:00'),
            ),
            const SizedBox(height: 10),
            Align(
              alignment: Alignment.centerRight,
              child: FilledButton(
                onPressed: _generating ? null : _generate,
                child: _generating
                    ? const SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(
                            strokeWidth: 2, color: Colors.black))
                    : const Text('Generate'),
              ),
            ),
            if (_explanation != null) ...[
              const SizedBox(height: 8),
              Text(_explanation!,
                  style: const TextStyle(
                      color: NurbyColors.accent, fontSize: 12)),
            ],
          ],
        ),
      ),
    );
  }

  List<Widget> _objectTriggerFields() {
    final labelsAsync = ref.watch(_labelsProvider);
    final labels = List<String>.from(labelsAsync.value ?? []);
    if (_label != null && !labels.contains(_label)) labels.insert(0, _label!);
    return [
      DropdownButtonFormField<String>(
        value: labels.contains(_label) ? _label : null,
        decoration: InputDecoration(
          labelText: 'Object',
          helperText: labelsAsync.hasError ? 'Could not load labels' : null,
        ),
        dropdownColor: NurbyColors.cardElevated,
        items: [
          for (final l in labels) DropdownMenuItem(value: l, child: Text(l)),
        ],
        onChanged: (v) => setState(() => _label = v),
      ),
      const SizedBox(height: 8),
      Row(
        children: [
          const Text('Confidence',
              style: TextStyle(
                  color: NurbyColors.mutedForeground, fontSize: 13)),
          Expanded(
            child: Slider(
              value: _confidence.clamp(0.5, 1.0),
              min: 0.5,
              max: 1.0,
              divisions: 10,
              activeColor: NurbyColors.accent,
              label: '${(_confidence * 100).round()}%',
              onChanged: (v) => setState(() => _confidence = v),
            ),
          ),
          Text('${(_confidence * 100).round()}%', style: monoStyle),
        ],
      ),
    ];
  }

  Widget _personTriggerField() {
    final personsAsync = ref.watch(_personsProvider);
    final persons = personsAsync.value ?? [];
    final ids = persons.map((p) => p.id).toSet();
    return DropdownButtonFormField<String>(
      value: ids.contains(_personId) ? _personId : null,
      decoration: InputDecoration(
        labelText: 'Person',
        helperText: personsAsync.hasError
            ? 'Could not load people'
            : (persons.isEmpty && !personsAsync.isLoading
                ? 'No known people yet'
                : null),
      ),
      dropdownColor: NurbyColors.cardElevated,
      items: [
        for (final p in persons)
          DropdownMenuItem(value: p.id, child: Text(p.displayName)),
      ],
      onChanged: (v) => setState(() => _personId = v),
    );
  }

  Widget _timeTile(String label, TimeOfDay? value,
      ValueChanged<TimeOfDay> onPicked) {
    return ListTile(
      dense: true,
      title: Text(label,
          style: const TextStyle(
              color: NurbyColors.mutedForeground, fontSize: 12)),
      subtitle: Text(value == null ? '--:--' : _fmtHhMm(value),
          style: monoStyle.copyWith(
              fontSize: 16, color: NurbyColors.foreground)),
      onTap: () async {
        final picked = await showTimePicker(
          context: context,
          initialTime: value ?? const TimeOfDay(hour: 22, minute: 0),
        );
        if (picked != null) onPicked(picked);
      },
    );
  }

  Widget _cameraPicker() {
    final camerasAsync = ref.watch(camerasProvider);
    final cameras = camerasAsync.value ?? [];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('Cameras (none selected = all)',
            style:
                TextStyle(color: NurbyColors.mutedForeground, fontSize: 12)),
        const SizedBox(height: 8),
        if (cameras.isEmpty)
          Text(camerasAsync.isLoading ? 'Loading cameras' : 'No cameras',
              style: const TextStyle(
                  color: NurbyColors.mutedForeground, fontSize: 12))
        else
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final c in cameras)
                FilterChip(
                  label: Text(c.name),
                  selected: _cameraIds.contains(c.id),
                  selectedColor: NurbyColors.accent.withValues(alpha: 0.2),
                  checkmarkColor: NurbyColors.accent,
                  onSelected: (sel) => setState(() {
                    if (sel) {
                      _cameraIds.add(c.id);
                    } else {
                      _cameraIds.remove(c.id);
                    }
                  }),
                ),
            ],
          ),
      ],
    );
  }

  List<Widget> _actionFields() {
    switch (_actionType) {
      case 'telegram':
        final channelsAsync = ref.watch(_channelsProvider);
        final channels = channelsAsync.value ?? [];
        final ids = channels.map((c) => c['id'].toString()).toSet();
        return [
          DropdownButtonFormField<String>(
            value: ids.contains(_channelId) ? _channelId : null,
            decoration: InputDecoration(
              labelText: 'Channel',
              helperText: channelsAsync.hasError
                  ? 'Could not load channels'
                  : (channels.isEmpty && !channelsAsync.isLoading
                      ? 'No Telegram channels configured'
                      : null),
            ),
            dropdownColor: NurbyColors.cardElevated,
            items: [
              for (final c in channels)
                DropdownMenuItem(
                  value: c['id'].toString(),
                  child: Text(c['name']?.toString() ?? c['id'].toString()),
                ),
            ],
            onChanged: (v) => setState(() => _channelId = v),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _message,
            decoration: const InputDecoration(
                labelText: 'Message', hintText: 'Alert text to send'),
          ),
        ];
      case 'email':
        return [
          TextField(
            controller: _recipients,
            decoration: const InputDecoration(
              labelText: 'Recipients',
              hintText: 'alice@example.com, bob@example.com',
            ),
            keyboardType: TextInputType.emailAddress,
          ),
        ];
      case 'device':
        final devicesAsync = ref.watch(_devicesProvider);
        final devices = devicesAsync.value ?? [];
        final ids = devices.map((d) => d['id'].toString()).toSet();
        return [
          DropdownButtonFormField<String>(
            value: ids.contains(_deviceId) ? _deviceId : null,
            decoration: InputDecoration(
              labelText: 'Device',
              helperText: devicesAsync.hasError
                  ? 'Could not load devices'
                  : (devices.isEmpty && !devicesAsync.isLoading
                      ? 'No devices registered'
                      : null),
            ),
            dropdownColor: NurbyColors.cardElevated,
            items: [
              for (final d in devices)
                DropdownMenuItem(
                  value: d['id'].toString(),
                  child: Text(d['name']?.toString() ?? d['id'].toString()),
                ),
            ],
            onChanged: (v) => setState(() => _deviceId = v),
          ),
        ];
    }
    return const [];
  }

  Widget _sectionLabel(String text) {
    return Padding(
      padding: const EdgeInsets.only(top: 18, bottom: 8, left: 4),
      child: Text(
        text,
        style: const TextStyle(
          fontFamily: 'Menlo',
          fontSize: 10,
          letterSpacing: 1.4,
          color: NurbyColors.accent,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }
}
