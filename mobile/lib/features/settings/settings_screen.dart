import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../models/models.dart';

// ---- Section data providers (invalidated locally after mutations) ----

final _statusProvider = FutureProvider<SystemStatus>(
    (ref) => ref.watch(systemRepoProvider).status());

final _healthProvider = FutureProvider<Map<String, dynamic>>(
    (ref) => ref.watch(systemRepoProvider).health());

final _versionProvider = FutureProvider<String>((ref) async {
  final j = await ref.watch(apiClientProvider).getJson('/api/system/version');
  return (j is Map ? j['version']?.toString() : null) ?? '?';
});

final _providersListProvider =
    FutureProvider<List<Map<String, dynamic>>>((ref) async {
  final j = await ref.watch(apiClientProvider).getJson('/api/providers') as List;
  return j.whereType<Map>().map((p) => p.cast<String, dynamic>()).toList();
});

final _providerHealthProvider =
    FutureProvider<Map<String, dynamic>>((ref) async =>
        (await ref.watch(apiClientProvider).getJson('/api/providers/health')
                as Map)
            .cast<String, dynamic>());

final _storageProvider = FutureProvider<Map<String, dynamic>>(
    (ref) => ref.watch(systemRepoProvider).storage());

final _telegramChannelsProvider =
    FutureProvider<List<Map<String, dynamic>>>((ref) async {
  final j = await ref.watch(apiClientProvider).getJson('/api/telegram/channels')
      as List;
  return j.whereType<Map>().map((c) => c.cast<String, dynamic>()).toList();
});

final _smtpProvider = FutureProvider<Map<String, dynamic>>((ref) async =>
    (await ref.watch(apiClientProvider).getJson('/api/smtp') as Map)
        .cast<String, dynamic>());

final _systemSettingsProvider = FutureProvider<Map<String, dynamic>>(
    (ref) async =>
        (await ref.watch(apiClientProvider).getJson('/api/system/settings')
                as Map)
            .cast<String, dynamic>());

final _usersProvider = FutureProvider<List<Map<String, dynamic>>>((ref) async {
  final j = await ref.watch(apiClientProvider).getJson('/api/users') as List;
  return j.whereType<Map>().map((u) => u.cast<String, dynamic>()).toList();
});

final _invitesProvider =
    FutureProvider<List<Map<String, dynamic>>>((ref) async {
  final j = await ref.watch(apiClientProvider).getJson('/api/invites') as List;
  return j.whereType<Map>().map((i) => i.cast<String, dynamic>()).toList();
});

final _apiKeysProvider =
    FutureProvider<List<Map<String, dynamic>>>((ref) async {
  final j = await ref.watch(apiClientProvider).getJson('/api/api-keys') as List;
  return j.whereType<Map>().map((k) => k.cast<String, dynamic>()).toList();
});

// ---- Shared helpers ----

void _snack(BuildContext context, String message) {
  ScaffoldMessenger.of(context)
      .showSnackBar(SnackBar(content: Text(message)));
}

/// Runs a mutation; on failure shows apiErrorMessage, on success refreshes.
Future<void> _mutate(
  BuildContext context,
  Future<void> Function() action,
  void Function() refresh,
) async {
  try {
    await action();
    refresh();
  } catch (e) {
    if (context.mounted) _snack(context, apiErrorMessage(e));
  }
}

Future<bool> _confirm(BuildContext context, String title, String message,
    {String action = 'Delete'}) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      backgroundColor: NurbyColors.cardElevated,
      title: Text(title),
      content: Text(message),
      actions: [
        TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel')),
        TextButton(
          onPressed: () => Navigator.pop(ctx, true),
          child:
              Text(action, style: const TextStyle(color: NurbyColors.danger)),
        ),
      ],
    ),
  );
  return ok ?? false;
}

String _fmtGb(num? bytes) {
  final gb = (bytes ?? 0) / (1024 * 1024 * 1024);
  return '${gb >= 100 ? gb.toStringAsFixed(0) : gb.toStringAsFixed(2)} GB';
}

String _fmtUptime(double? seconds) {
  if (seconds == null) return '?';
  final d = Duration(seconds: seconds.round());
  if (d.inDays > 0) return '${d.inDays}d ${d.inHours % 24}h';
  if (d.inHours > 0) return '${d.inHours}h ${d.inMinutes % 60}m';
  return '${d.inMinutes}m';
}

Widget _async<T>(AsyncValue<T> value, Widget Function(T data) builder) {
  return value.when(
    loading: () => const Padding(
      padding: EdgeInsets.all(16),
      child: Center(
        child: SizedBox(
            width: 18,
            height: 18,
            child: CircularProgressIndicator(strokeWidth: 2)),
      ),
    ),
    error: (e, _) => Padding(
      padding: const EdgeInsets.all(12),
      child: Text(apiErrorMessage(e),
          style:
              const TextStyle(color: NurbyColors.mutedForeground, fontSize: 13)),
    ),
    data: builder,
  );
}

Widget _kvRow(String label, String value) {
  return Padding(
    padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
    child: Row(
      children: [
        Expanded(
          child: Text(label,
              style: const TextStyle(
                  color: NurbyColors.mutedForeground, fontSize: 13)),
        ),
        Text(value, style: monoStyle.copyWith(color: NurbyColors.foreground)),
      ],
    ),
  );
}

Widget _subLabel(String text) {
  return Padding(
    padding: const EdgeInsets.only(top: 12, bottom: 4, left: 4),
    child: Align(
      alignment: Alignment.centerLeft,
      child: Text(
        text,
        style: const TextStyle(
          fontFamily: 'Menlo',
          fontSize: 10,
          letterSpacing: 1.2,
          color: NurbyColors.mutedForeground,
          fontWeight: FontWeight.w600,
        ),
      ),
    ),
  );
}

Widget _emptyNote(String text) {
  return Padding(
    padding: const EdgeInsets.all(8),
    child: Text(text,
        style:
            const TextStyle(color: NurbyColors.mutedForeground, fontSize: 13)),
  );
}

/// Shows a secret exactly once in a copyable dialog.
Future<void> _showSecretDialog(
    BuildContext context, String title, String secret) {
  return showDialog<void>(
    context: context,
    builder: (ctx) => AlertDialog(
      backgroundColor: NurbyColors.cardElevated,
      title: Text(title),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: double.maxFinite,
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: NurbyColors.card,
              border: Border.all(color: NurbyColors.border),
              borderRadius: BorderRadius.circular(8),
            ),
            child: SelectableText(
              secret,
              style: monoStyle.copyWith(
                  fontSize: 13, color: NurbyColors.foreground),
            ),
          ),
          const SizedBox(height: 8),
          const Text('Copy it now. It will not be shown again.',
              style: TextStyle(
                  color: NurbyColors.mutedForeground, fontSize: 12)),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () async {
            await Clipboard.setData(ClipboardData(text: secret));
            if (ctx.mounted) _snack(ctx, 'Copied to clipboard');
          },
          child: const Text('Copy'),
        ),
        TextButton(
            onPressed: () => Navigator.pop(ctx), child: const Text('Done')),
      ],
    ),
  );
}

/// Collapsible section styled as a Nurby card with a mono accent label.
class _Section extends StatelessWidget {
  const _Section({
    required this.title,
    required this.children,
    this.initiallyExpanded = false,
  });

  final String title;
  final List<Widget> children;
  final bool initiallyExpanded;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Card(
        child: Theme(
          data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
          child: ExpansionTile(
            initiallyExpanded: initiallyExpanded,
            maintainState: true,
            shape: const RoundedRectangleBorder(),
            collapsedShape: const RoundedRectangleBorder(),
            iconColor: NurbyColors.mutedForeground,
            collapsedIconColor: NurbyColors.mutedForeground,
            tilePadding: const EdgeInsets.symmetric(horizontal: 16),
            childrenPadding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
            title: Text(
              title,
              style: const TextStyle(
                fontFamily: 'Menlo',
                fontSize: 11,
                letterSpacing: 1.4,
                color: NurbyColors.accent,
                fontWeight: FontWeight.w600,
              ),
            ),
            children: children,
          ),
        ),
      ),
    );
  }
}

/// Settings: system status, AI providers, storage, notification channels,
/// system settings, access control, API keys and server connection.
class SettingsScreen extends ConsumerWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final user = ref.watch(authProvider).user;
    final isAdmin = user?.isAdmin ?? false;

    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          const _SystemSection(),
          const _ProvidersSection(),
          const _StorageSection(),
          const _NotificationChannelsSection(),
          const _SystemSettingsSection(),
          if (isAdmin) const _AccessSection(),
          const _ApiKeysSection(),
          const _ServerSection(),
          const SizedBox(height: 24),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------- SYSTEM

class _SystemSection extends ConsumerStatefulWidget {
  const _SystemSection();

  @override
  ConsumerState<_SystemSection> createState() => _SystemSectionState();
}

class _SystemSectionState extends ConsumerState<_SystemSection> {
  List<Map<String, dynamic>>? _doctorChecks;
  bool _doctorRunning = false;

  Future<void> _runDoctor() async {
    setState(() => _doctorRunning = true);
    try {
      final checks = await ref.read(systemRepoProvider).doctor();
      if (mounted) setState(() => _doctorChecks = checks);
    } catch (e) {
      if (mounted) _snack(context, apiErrorMessage(e));
    } finally {
      if (mounted) setState(() => _doctorRunning = false);
    }
  }

  Color _checkColor(String? status) => switch (status) {
        'ok' => NurbyColors.accent,
        'warn' => NurbyColors.warning,
        _ => NurbyColors.danger,
      };

  @override
  Widget build(BuildContext context) {
    final version = ref.watch(_versionProvider);
    final status = ref.watch(_statusProvider);
    final health = ref.watch(_healthProvider);

    return _Section(
      title: 'SYSTEM',
      initiallyExpanded: true,
      children: [
        _kvRow('Version', version.value ?? '…'),
        _async(status, (s) {
          return Column(children: [
            _kvRow('Cameras',
                '${s.camerasOnline}/${s.camerasTotal} online, ${s.camerasRecording} recording'),
            _kvRow('Uptime', _fmtUptime(s.uptimeSeconds)),
          ]);
        }),
        _async(health, (h) {
          final mem = (h['mem'] as Map?)?.cast<String, dynamic>() ?? const {};
          final disk = (h['disk'] as Map?)?.cast<String, dynamic>() ?? const {};
          final cpu = h['cpu_percent'];
          return Column(children: [
            _kvRow(
                'CPU',
                cpu is num
                    ? '${cpu.toStringAsFixed(0)}% of ${h['cpu_count'] ?? '?'} cores'
                    : '?'),
            _kvRow('Memory',
                '${_fmtGb(mem['used_bytes'] as num?)} / ${_fmtGb(mem['total_bytes'] as num?)}'),
            _kvRow('Disk',
                '${_fmtGb(disk['used_bytes'] as num?)} / ${_fmtGb(disk['total_bytes'] as num?)}'),
          ]);
        }),
        const SizedBox(height: 8),
        Align(
          alignment: Alignment.centerLeft,
          child: OutlinedButton.icon(
            onPressed: _doctorRunning ? null : _runDoctor,
            icon: _doctorRunning
                ? const SizedBox(
                    width: 14,
                    height: 14,
                    child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.health_and_safety_outlined, size: 18),
            label: const Text('Run doctor'),
          ),
        ),
        if (_doctorChecks != null) ...[
          const SizedBox(height: 4),
          if (_doctorChecks!.isEmpty) _emptyNote('No checks reported'),
          for (final c in _doctorChecks!)
            ListTile(
              dense: true,
              contentPadding: const EdgeInsets.symmetric(horizontal: 4),
              leading: Container(
                width: 10,
                height: 10,
                decoration: BoxDecoration(
                  color: _checkColor(c['status'] as String?),
                  shape: BoxShape.circle,
                ),
              ),
              title: Text(c['label']?.toString() ?? c['id']?.toString() ?? '?',
                  style: const TextStyle(fontSize: 13)),
              subtitle: c['detail'] != null
                  ? Text(c['detail'].toString(),
                      style: const TextStyle(
                          color: NurbyColors.mutedForeground, fontSize: 12))
                  : null,
              trailing: c['latency_ms'] != null
                  ? Text('${c['latency_ms']} ms', style: monoStyle)
                  : null,
            ),
        ],
      ],
    );
  }
}

// ----------------------------------------------------------- AI PROVIDERS

const _providerKinds = [
  'ollama',
  'openai',
  'anthropic',
  'gemini',
  'azure-openai',
];

class _ProvidersSection extends ConsumerWidget {
  const _ProvidersSection();

  Future<void> _test(
      BuildContext context, WidgetRef ref, Map<String, dynamic> p) async {
    try {
      final j = await ref
          .read(apiClientProvider)
          .postJson('/api/providers/${p['id']}/test') as Map;
      final ok = j['ok'] == true;
      final msg = j['message']?.toString() ?? (ok ? 'OK' : 'Failed');
      final latency = j['latency_ms'];
      if (context.mounted) {
        _snack(context, latency != null ? '$msg ($latency ms)' : msg);
      }
    } catch (e) {
      if (context.mounted) _snack(context, apiErrorMessage(e));
    }
  }

  Future<void> _addOrEdit(BuildContext context, WidgetRef ref,
      [Map<String, dynamic>? existing]) async {
    final body = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (_) => _ProviderDialog(initial: existing),
    );
    if (body == null || !context.mounted) return;
    await _mutate(context, () async {
      final api = ref.read(apiClientProvider);
      if (existing == null) {
        await api.postJson('/api/providers', body: body);
      } else {
        await api.patchJson('/api/providers/${existing['id']}', body: body);
      }
    }, () {
      ref.invalidate(_providersListProvider);
      ref.invalidate(_providerHealthProvider);
    });
  }

  Future<void> _delete(
      BuildContext context, WidgetRef ref, Map<String, dynamic> p) async {
    final ok = await _confirm(context, 'Delete provider?',
        '"${p['name']}" will be removed. Rules using it may stop working.');
    if (!ok || !context.mounted) return;
    await _mutate(
        context,
        () => ref.read(apiClientProvider).delete('/api/providers/${p['id']}'),
        () {
      ref.invalidate(_providersListProvider);
      ref.invalidate(_providerHealthProvider);
    });
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final health = ref.watch(_providerHealthProvider);
    final providers = ref.watch(_providersListProvider);

    return _Section(
      title: 'AI PROVIDERS',
      children: [
        _async(health, (h) {
          final configured = h['configured'] == true;
          final reachable = h['reachable'] == true;
          final color = !configured
              ? NurbyColors.warning
              : reachable
                  ? NurbyColors.accent
                  : NurbyColors.danger;
          final text = !configured
              ? 'No AI provider configured'
              : reachable
                  ? '${h['name'] ?? 'Provider'} (${h['kind'] ?? '?'}) reachable'
                  : h['message']?.toString() ??
                      '${h['name'] ?? 'Provider'} unreachable';
          return Container(
            width: double.infinity,
            margin: const EdgeInsets.only(bottom: 8),
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.12),
              border: Border.all(color: color.withValues(alpha: 0.4)),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Text(text, style: TextStyle(color: color, fontSize: 13)),
          );
        }),
        _async(providers, (list) {
          if (list.isEmpty) return _emptyNote('No providers configured');
          return Column(children: [
            for (final p in list)
              ListTile(
                contentPadding: const EdgeInsets.symmetric(horizontal: 4),
                title: Text(p['name']?.toString() ?? '?',
                    style: const TextStyle(fontSize: 14)),
                subtitle: Text(
                  [
                    p['kind']?.toString() ?? '?',
                    if (p['default_model'] != null &&
                        '${p['default_model']}'.isNotEmpty)
                      p['default_model'].toString(),
                  ].join(' · '),
                  style: monoStyle,
                ),
                trailing: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    IconButton(
                      visualDensity: VisualDensity.compact,
                      icon: const Icon(Icons.bolt_outlined,
                          size: 20, color: NurbyColors.mutedForeground),
                      tooltip: 'Test',
                      onPressed: () => _test(context, ref, p),
                    ),
                    IconButton(
                      visualDensity: VisualDensity.compact,
                      icon: const Icon(Icons.edit_outlined,
                          size: 18, color: NurbyColors.mutedForeground),
                      tooltip: 'Edit',
                      onPressed: () => _addOrEdit(context, ref, p),
                    ),
                    IconButton(
                      visualDensity: VisualDensity.compact,
                      icon: const Icon(Icons.delete_outline,
                          size: 18, color: NurbyColors.danger),
                      tooltip: 'Delete',
                      onPressed: () => _delete(context, ref, p),
                    ),
                  ],
                ),
              ),
          ]);
        }),
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            onPressed: () => _addOrEdit(context, ref),
            icon: const Icon(Icons.add, size: 18),
            label: const Text('Add provider'),
          ),
        ),
      ],
    );
  }
}

class _ProviderDialog extends StatefulWidget {
  const _ProviderDialog({this.initial});
  final Map<String, dynamic>? initial;

  @override
  State<_ProviderDialog> createState() => _ProviderDialogState();
}

class _ProviderDialogState extends State<_ProviderDialog> {
  late final TextEditingController _name;
  late final TextEditingController _baseUrl;
  late final TextEditingController _apiKey;
  late final TextEditingController _model;
  late String _kind;

  @override
  void initState() {
    super.initState();
    final i = widget.initial;
    _name = TextEditingController(text: i?['name']?.toString() ?? '');
    _baseUrl = TextEditingController(text: i?['base_url']?.toString() ?? '');
    _apiKey = TextEditingController();
    _model =
        TextEditingController(text: i?['default_model']?.toString() ?? '');
    final kind = i?['kind']?.toString();
    _kind = _providerKinds.contains(kind) ? kind! : _providerKinds.first;
  }

  @override
  void dispose() {
    _name.dispose();
    _baseUrl.dispose();
    _apiKey.dispose();
    _model.dispose();
    super.dispose();
  }

  void _save() {
    if (_name.text.trim().isEmpty) return;
    final body = <String, dynamic>{
      'name': _name.text.trim(),
      'kind': _kind,
      if (_baseUrl.text.trim().isNotEmpty) 'base_url': _baseUrl.text.trim(),
      if (_apiKey.text.trim().isNotEmpty) 'api_key': _apiKey.text.trim(),
      if (_model.text.trim().isNotEmpty)
        'default_model': _model.text.trim(),
    };
    Navigator.pop(context, body);
  }

  @override
  Widget build(BuildContext context) {
    final editing = widget.initial != null;
    return AlertDialog(
      backgroundColor: NurbyColors.cardElevated,
      title: Text(editing ? 'Edit provider' : 'Add provider'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: _name,
              decoration: const InputDecoration(labelText: 'Name'),
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              value: _kind,
              dropdownColor: NurbyColors.cardElevated,
              decoration: const InputDecoration(labelText: 'Kind'),
              items: [
                for (final k in _providerKinds)
                  DropdownMenuItem(value: k, child: Text(k)),
              ],
              onChanged: (v) => setState(() => _kind = v ?? _kind),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _baseUrl,
              decoration: const InputDecoration(
                  labelText: 'Base URL (optional)'),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _apiKey,
              obscureText: true,
              decoration: InputDecoration(
                labelText:
                    editing ? 'API key (blank = unchanged)' : 'API key',
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _model,
              decoration: const InputDecoration(labelText: 'Default model'),
            ),
          ],
        ),
      ),
      actions: [
        TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel')),
        TextButton(
          onPressed: _save,
          child: const Text('Save'),
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------- STORAGE

class _StorageSection extends ConsumerWidget {
  const _StorageSection();

  String _cameraName(List<Camera> cameras, String id) {
    for (final c in cameras) {
      if (c.id == id) return c.name;
    }
    return id.length > 8 ? id.substring(0, 8) : id;
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final storage = ref.watch(_storageProvider);
    final cameras = ref.watch(camerasProvider).value ?? const <Camera>[];

    return _Section(
      title: 'STORAGE',
      children: [
        _async(storage, (s) {
          final perCamera = (s['cameras'] as List? ?? [])
              .whereType<Map>()
              .map((c) => c.cast<String, dynamic>())
              .toList();
          return Column(children: [
            _kvRow('Total recordings',
                _fmtGb(s['total_recording_bytes'] as num?)),
            _kvRow('Total observations', '${s['total_observations'] ?? 0}'),
            if (perCamera.isEmpty)
              _emptyNote('No per-camera storage data')
            else
              for (final c in perCamera)
                ListTile(
                  dense: true,
                  contentPadding: const EdgeInsets.symmetric(horizontal: 4),
                  title: Text(
                      _cameraName(cameras, c['camera_id']?.toString() ?? ''),
                      style: const TextStyle(fontSize: 13)),
                  subtitle: Text(
                    '${c['recording_count'] ?? 0} recordings · '
                    '${c['observation_count'] ?? 0} observations',
                    style: const TextStyle(
                        color: NurbyColors.mutedForeground, fontSize: 12),
                  ),
                  trailing: Text(_fmtGb(c['recording_bytes'] as num?),
                      style: monoStyle.copyWith(
                          color: NurbyColors.foreground)),
                ),
          ]);
        }),
      ],
    );
  }
}

// ------------------------------------------------ NOTIFICATION CHANNELS

class _NotificationChannelsSection extends ConsumerWidget {
  const _NotificationChannelsSection();

  Future<void> _addTelegram(BuildContext context, WidgetRef ref) async {
    final nameCtrl = TextEditingController();
    final tokenCtrl = TextEditingController();
    final chatCtrl = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: NurbyColors.cardElevated,
        title: const Text('Add Telegram channel'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: nameCtrl,
                decoration: const InputDecoration(labelText: 'Name'),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: tokenCtrl,
                decoration: const InputDecoration(labelText: 'Bot token'),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: chatCtrl,
                decoration:
                    const InputDecoration(labelText: 'Chat ID (optional)'),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Cancel')),
          TextButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Add')),
        ],
      ),
    );
    if (ok != true || !context.mounted) return;
    await _mutate(context, () async {
      await ref.read(apiClientProvider).postJson('/api/telegram/channels',
          body: {
            'name': nameCtrl.text.trim(),
            'token': tokenCtrl.text.trim(),
            if (chatCtrl.text.trim().isNotEmpty)
              'chat_id': chatCtrl.text.trim(),
          });
    }, () => ref.invalidate(_telegramChannelsProvider));
  }

  Future<void> _testTelegram(
      BuildContext context, WidgetRef ref, Map<String, dynamic> ch) async {
    try {
      final j = await ref
          .read(apiClientProvider)
          .postJson('/api/telegram/channels/${ch['id']}/test');
      final msg = j is Map
          ? (j['message']?.toString() ??
              (j['ok'] == true || j['success'] == true
                  ? 'Test message sent'
                  : 'Test failed'))
          : 'Test message sent';
      if (context.mounted) _snack(context, msg);
    } catch (e) {
      if (context.mounted) _snack(context, apiErrorMessage(e));
    }
  }

  Future<void> _deleteTelegram(
      BuildContext context, WidgetRef ref, Map<String, dynamic> ch) async {
    final ok = await _confirm(context, 'Delete channel?',
        '"${ch['name']}" will no longer receive alerts.');
    if (!ok || !context.mounted) return;
    await _mutate(
        context,
        () => ref
            .read(apiClientProvider)
            .delete('/api/telegram/channels/${ch['id']}'),
        () => ref.invalidate(_telegramChannelsProvider));
  }

  Future<void> _openSmtp(BuildContext context, WidgetRef ref) async {
    Map<String, dynamic> initial = const {};
    try {
      initial = await ref.read(_smtpProvider.future);
    } catch (_) {
      // Not configured yet; open the dialog with blank fields.
    }
    if (!context.mounted) return;
    await showDialog<void>(
      context: context,
      builder: (_) => _SmtpDialog(initial: initial),
    );
    ref.invalidate(_smtpProvider);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final channels = ref.watch(_telegramChannelsProvider);

    return _Section(
      title: 'NOTIFICATION CHANNELS',
      children: [
        _subLabel('TELEGRAM'),
        _async(channels, (list) {
          if (list.isEmpty) return _emptyNote('No Telegram channels');
          return Column(children: [
            for (final ch in list)
              ListTile(
                contentPadding: const EdgeInsets.symmetric(horizontal: 4),
                title: Text(ch['name']?.toString() ?? '?',
                    style: const TextStyle(fontSize: 14)),
                subtitle: ch['chat_id'] != null
                    ? Text('chat ${ch['chat_id']}', style: monoStyle)
                    : null,
                trailing: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    IconButton(
                      visualDensity: VisualDensity.compact,
                      icon: const Icon(Icons.send_outlined,
                          size: 18, color: NurbyColors.mutedForeground),
                      tooltip: 'Send test',
                      onPressed: () => _testTelegram(context, ref, ch),
                    ),
                    IconButton(
                      visualDensity: VisualDensity.compact,
                      icon: const Icon(Icons.delete_outline,
                          size: 18, color: NurbyColors.danger),
                      tooltip: 'Delete',
                      onPressed: () => _deleteTelegram(context, ref, ch),
                    ),
                  ],
                ),
              ),
          ]);
        }),
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            onPressed: () => _addTelegram(context, ref),
            icon: const Icon(Icons.add, size: 18),
            label: const Text('Add Telegram channel'),
          ),
        ),
        _subLabel('EMAIL'),
        ListTile(
          contentPadding: const EdgeInsets.symmetric(horizontal: 4),
          title: const Text('SMTP', style: TextStyle(fontSize: 14)),
          subtitle: const Text('Outgoing email configuration',
              style: TextStyle(
                  color: NurbyColors.mutedForeground, fontSize: 12)),
          trailing: const Icon(Icons.edit_outlined,
              size: 18, color: NurbyColors.mutedForeground),
          onTap: () => _openSmtp(context, ref),
        ),
      ],
    );
  }
}

class _SmtpDialog extends ConsumerStatefulWidget {
  const _SmtpDialog({required this.initial});
  final Map<String, dynamic> initial;

  @override
  ConsumerState<_SmtpDialog> createState() => _SmtpDialogState();
}

class _SmtpDialogState extends ConsumerState<_SmtpDialog> {
  static const _knownKeys = [
    'smtp_host',
    'smtp_port',
    'smtp_from',
    'smtp_username',
    'smtp_password',
  ];

  late final Map<String, TextEditingController> _fields;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    final keys = <String>[..._knownKeys];
    for (final entry in widget.initial.entries) {
      final v = entry.value;
      if (!keys.contains(entry.key) &&
          entry.key.startsWith('smtp_') &&
          (v == null || v is String || v is num)) {
        keys.add(entry.key);
      }
    }
    _fields = {
      for (final k in keys)
        k: TextEditingController(text: widget.initial[k]?.toString() ?? ''),
    };
  }

  @override
  void dispose() {
    for (final c in _fields.values) {
      c.dispose();
    }
    super.dispose();
  }

  String _label(String key) =>
      key.replaceFirst('smtp_', '').replaceAll('_', ' ');

  Map<String, dynamic> _body() {
    final body = <String, dynamic>{};
    _fields.forEach((key, ctrl) {
      final text = ctrl.text.trim();
      if (key.contains('port')) {
        body[key] = int.tryParse(text) ?? 0;
      } else {
        body[key] = text;
      }
    });
    return body;
  }

  Future<void> _save() async {
    setState(() => _busy = true);
    try {
      await ref
          .read(apiClientProvider)
          .dio
          .put<dynamic>('/api/smtp', data: _body());
      if (mounted) {
        _snack(context, 'SMTP settings saved');
        Navigator.pop(context);
      }
    } catch (e) {
      if (mounted) _snack(context, apiErrorMessage(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _sendTest() async {
    setState(() => _busy = true);
    try {
      final j =
          await ref.read(apiClientProvider).postJson('/api/smtp-test') as Map;
      final msg = j['message']?.toString() ??
          (j['success'] == true ? 'Test email sent' : 'Test failed');
      if (mounted) _snack(context, msg);
    } catch (e) {
      if (mounted) _snack(context, apiErrorMessage(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: NurbyColors.cardElevated,
      title: const Text('SMTP settings'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            for (final entry in _fields.entries) ...[
              TextField(
                controller: entry.value,
                obscureText: entry.key.contains('password'),
                keyboardType: entry.key.contains('port')
                    ? TextInputType.number
                    : TextInputType.text,
                decoration: InputDecoration(labelText: _label(entry.key)),
              ),
              const SizedBox(height: 12),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: _busy ? null : _sendTest,
          child: const Text('Send test'),
        ),
        TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel')),
        TextButton(
          onPressed: _busy ? null : _save,
          child: const Text('Save'),
        ),
      ],
    );
  }
}

// -------------------------------------------------------- SYSTEM SETTINGS

class _SystemSettingsSection extends ConsumerWidget {
  const _SystemSettingsSection();

  Future<void> _patchKey(BuildContext context, WidgetRef ref, String key,
      Object? value) async {
    await _mutate(
        context,
        () => ref
            .read(apiClientProvider)
            .patchJson('/api/system/settings', body: {key: value}),
        () => ref.invalidate(_systemSettingsProvider));
  }

  Future<void> _editValue(BuildContext context, WidgetRef ref, String key,
      Object? current) async {
    final controller = TextEditingController(text: current?.toString() ?? '');
    final result = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: NurbyColors.cardElevated,
        title: Text(key),
        content: TextField(
          controller: controller,
          keyboardType:
              current is num ? TextInputType.number : TextInputType.text,
          decoration: const InputDecoration(hintText: 'Value'),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Cancel')),
          TextButton(
              onPressed: () => Navigator.pop(ctx, controller.text),
              child: const Text('Save')),
        ],
      ),
    );
    if (result == null || !context.mounted) return;
    Object? value = result;
    if (current is int) {
      value = int.tryParse(result) ?? current;
    } else if (current is double) {
      value = double.tryParse(result) ?? current;
    } else if (current is num) {
      value = num.tryParse(result) ?? current;
    }
    await _patchKey(context, ref, key, value);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final settings = ref.watch(_systemSettingsProvider);

    return _Section(
      title: 'SYSTEM SETTINGS',
      children: [
        _async(settings, (map) {
          if (map.isEmpty) return _emptyNote('No settings exposed');
          final entries = map.entries.toList()
            ..sort((a, b) => a.key.compareTo(b.key));
          return Column(children: [
            for (final e in entries)
              if (e.value is bool)
                SwitchListTile(
                  contentPadding:
                      const EdgeInsets.symmetric(horizontal: 4),
                  dense: true,
                  title: Text(e.key, style: const TextStyle(fontSize: 13)),
                  value: e.value as bool,
                  activeColor: NurbyColors.accent,
                  onChanged: (v) => _patchKey(context, ref, e.key, v),
                )
              else if (e.value is num || e.value is String || e.value == null)
                ListTile(
                  contentPadding:
                      const EdgeInsets.symmetric(horizontal: 4),
                  dense: true,
                  title: Text(e.key, style: const TextStyle(fontSize: 13)),
                  trailing: Text(
                    e.value?.toString() ?? '—',
                    style:
                        monoStyle.copyWith(color: NurbyColors.foreground),
                  ),
                  onTap: () => _editValue(context, ref, e.key, e.value),
                )
              else
                ListTile(
                  contentPadding:
                      const EdgeInsets.symmetric(horizontal: 4),
                  dense: true,
                  title: Text(e.key, style: const TextStyle(fontSize: 13)),
                  subtitle: Text(e.value.toString(),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: monoStyle),
                ),
          ]);
        }),
      ],
    );
  }
}

// ------------------------------------------------------------------ ACCESS

const _userRoles = ['admin', 'viewer', 'guardian'];

class _AccessSection extends ConsumerWidget {
  const _AccessSection();

  Future<void> _deleteUser(
      BuildContext context, WidgetRef ref, Map<String, dynamic> u) async {
    final ok = await _confirm(context, 'Delete user?',
        '${u['email']} will lose access permanently.');
    if (!ok || !context.mounted) return;
    await _mutate(
        context,
        () => ref.read(apiClientProvider).delete('/api/users/${u['id']}'),
        () => ref.invalidate(_usersProvider));
  }

  Future<void> _createInvite(BuildContext context, WidgetRef ref) async {
    var role = 'viewer';
    final usesCtrl = TextEditingController(text: '1');
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setState) => AlertDialog(
          backgroundColor: NurbyColors.cardElevated,
          title: const Text('Create invite'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              DropdownButtonFormField<String>(
                value: role,
                dropdownColor: NurbyColors.cardElevated,
                decoration: const InputDecoration(labelText: 'Role'),
                items: [
                  for (final r in _userRoles)
                    DropdownMenuItem(value: r, child: Text(r)),
                ],
                onChanged: (v) => setState(() => role = v ?? role),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: usesCtrl,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(labelText: 'Max uses'),
              ),
            ],
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(ctx, false),
                child: const Text('Cancel')),
            TextButton(
                onPressed: () => Navigator.pop(ctx, true),
                child: const Text('Create')),
          ],
        ),
      ),
    );
    if (ok != true || !context.mounted) return;
    try {
      final j = await ref.read(apiClientProvider).postJson('/api/invites',
          body: {
            'role': role,
            'max_uses': int.tryParse(usesCtrl.text.trim()) ?? 1,
          }) as Map;
      ref.invalidate(_invitesProvider);
      final key = j['key']?.toString() ?? j['invite_key']?.toString() ?? '';
      if (context.mounted && key.isNotEmpty) {
        await _showSecretDialog(context, 'Invite key', key);
      }
    } catch (e) {
      if (context.mounted) _snack(context, apiErrorMessage(e));
    }
  }

  Future<void> _revokeInvite(
      BuildContext context, WidgetRef ref, Map<String, dynamic> inv) async {
    final ok = await _confirm(context, 'Revoke invite?',
        'This invite key will stop working immediately.',
        action: 'Revoke');
    if (!ok || !context.mounted) return;
    await _mutate(
        context,
        () => ref.read(apiClientProvider).delete('/api/invites/${inv['id']}'),
        () => ref.invalidate(_invitesProvider));
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final users = ref.watch(_usersProvider);
    final invites = ref.watch(_invitesProvider);
    final currentUserId = ref.watch(authProvider).user?.id;

    return _Section(
      title: 'ACCESS',
      children: [
        _subLabel('USERS'),
        _async(users, (list) {
          if (list.isEmpty) return _emptyNote('No users');
          return Column(children: [
            for (final u in list) ...[
              ListTile(
                contentPadding: const EdgeInsets.symmetric(horizontal: 4),
                title: Text(
                  u['display_name']?.toString() ??
                      u['email']?.toString() ??
                      '?',
                  style: const TextStyle(fontSize: 14),
                ),
                subtitle:
                    Text(u['email']?.toString() ?? '', style: monoStyle),
                trailing: u['id'] == currentUserId
                    ? const Text('you', style: monoStyle)
                    : IconButton(
                        visualDensity: VisualDensity.compact,
                        icon: const Icon(Icons.delete_outline,
                            size: 18, color: NurbyColors.danger),
                        tooltip: 'Delete',
                        onPressed: () => _deleteUser(context, ref, u),
                      ),
              ),
              Padding(
                padding: const EdgeInsets.only(left: 4, right: 4, bottom: 6),
                child: Row(
                  children: [
                    DropdownButton<String>(
                      value: _userRoles.contains(u['role'])
                          ? u['role'] as String
                          : 'viewer',
                      dropdownColor: NurbyColors.cardElevated,
                      underline: const SizedBox.shrink(),
                      style: const TextStyle(
                          color: NurbyColors.foreground, fontSize: 13),
                      items: [
                        for (final r in _userRoles)
                          DropdownMenuItem(value: r, child: Text(r)),
                      ],
                      onChanged: u['id'] == currentUserId
                          ? null
                          : (v) {
                              if (v == null) return;
                              _mutate(
                                  context,
                                  () => ref.read(apiClientProvider).patchJson(
                                      '/api/users/${u['id']}',
                                      body: {'role': v}),
                                  () => ref.invalidate(_usersProvider));
                            },
                    ),
                    const Spacer(),
                    const Text('Active',
                        style: TextStyle(
                            color: NurbyColors.mutedForeground,
                            fontSize: 13)),
                    Switch(
                      value: u['is_active'] as bool? ?? true,
                      activeColor: NurbyColors.accent,
                      onChanged: u['id'] == currentUserId
                          ? null
                          : (v) => _mutate(
                              context,
                              () => ref.read(apiClientProvider).patchJson(
                                  '/api/users/${u['id']}',
                                  body: {'is_active': v}),
                              () => ref.invalidate(_usersProvider)),
                    ),
                  ],
                ),
              ),
              const Divider(height: 1),
            ],
          ]);
        }),
        _subLabel('INVITE KEYS'),
        _async(invites, (list) {
          if (list.isEmpty) return _emptyNote('No active invites');
          return Column(children: [
            for (final inv in list)
              ListTile(
                contentPadding: const EdgeInsets.symmetric(horizontal: 4),
                dense: true,
                title: Text(
                  inv['key']?.toString() ?? inv['id']?.toString() ?? '?',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: monoStyle.copyWith(
                      fontSize: 12, color: NurbyColors.foreground),
                ),
                subtitle: Text(
                  [
                    inv['role']?.toString() ?? 'viewer',
                    'max ${inv['max_uses'] ?? 1} uses',
                    if (inv['expires_at'] != null)
                      'expires ${_fmtDate(inv['expires_at'])}',
                  ].join(' · '),
                  style: const TextStyle(
                      color: NurbyColors.mutedForeground, fontSize: 12),
                ),
                trailing: IconButton(
                  visualDensity: VisualDensity.compact,
                  icon: const Icon(Icons.delete_outline,
                      size: 18, color: NurbyColors.danger),
                  tooltip: 'Revoke',
                  onPressed: () => _revokeInvite(context, ref, inv),
                ),
              ),
          ]);
        }),
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            onPressed: () => _createInvite(context, ref),
            icon: const Icon(Icons.add, size: 18),
            label: const Text('Create invite'),
          ),
        ),
      ],
    );
  }

  static String _fmtDate(Object? iso) {
    final dt = DateTime.tryParse(iso?.toString() ?? '')?.toLocal();
    return dt == null ? '?' : DateFormat('MMM d, HH:mm').format(dt);
  }
}

// --------------------------------------------------------------- API KEYS

class _ApiKeysSection extends ConsumerWidget {
  const _ApiKeysSection();

  Future<void> _create(BuildContext context, WidgetRef ref) async {
    final nameCtrl = TextEditingController();
    var scope = 'read';
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setState) => AlertDialog(
          backgroundColor: NurbyColors.cardElevated,
          title: const Text('Create API key'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: nameCtrl,
                decoration: const InputDecoration(labelText: 'Name'),
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<String>(
                value: scope,
                dropdownColor: NurbyColors.cardElevated,
                decoration: const InputDecoration(labelText: 'Scope'),
                items: const [
                  DropdownMenuItem(value: 'read', child: Text('read')),
                  DropdownMenuItem(value: 'write', child: Text('write')),
                ],
                onChanged: (v) => setState(() => scope = v ?? scope),
              ),
            ],
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(ctx, false),
                child: const Text('Cancel')),
            TextButton(
                onPressed: () => Navigator.pop(ctx, true),
                child: const Text('Create')),
          ],
        ),
      ),
    );
    if (ok != true || !context.mounted) return;
    try {
      final j = await ref.read(apiClientProvider).postJson('/api/api-keys',
          body: {'name': nameCtrl.text.trim(), 'scope': scope}) as Map;
      ref.invalidate(_apiKeysProvider);
      final key = j['key']?.toString() ?? '';
      if (context.mounted && key.isNotEmpty) {
        await _showSecretDialog(context, 'API key', key);
      }
    } catch (e) {
      if (context.mounted) _snack(context, apiErrorMessage(e));
    }
  }

  Future<void> _revoke(
      BuildContext context, WidgetRef ref, Map<String, dynamic> k) async {
    final ok = await _confirm(context, 'Revoke API key?',
        '"${k['name']}" will stop working immediately.',
        action: 'Revoke');
    if (!ok || !context.mounted) return;
    await _mutate(
        context,
        () => ref.read(apiClientProvider).delete('/api/api-keys/${k['id']}'),
        () => ref.invalidate(_apiKeysProvider));
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final keys = ref.watch(_apiKeysProvider);

    return _Section(
      title: 'API KEYS',
      children: [
        _async(keys, (list) {
          if (list.isEmpty) return _emptyNote('No API keys');
          return Column(children: [
            for (final k in list)
              ListTile(
                contentPadding: const EdgeInsets.symmetric(horizontal: 4),
                dense: true,
                title: Text(k['name']?.toString() ?? '?',
                    style: const TextStyle(fontSize: 14)),
                subtitle:
                    Text(k['scope']?.toString() ?? 'read', style: monoStyle),
                trailing: IconButton(
                  visualDensity: VisualDensity.compact,
                  icon: const Icon(Icons.delete_outline,
                      size: 18, color: NurbyColors.danger),
                  tooltip: 'Revoke',
                  onPressed: () => _revoke(context, ref, k),
                ),
              ),
          ]);
        }),
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            onPressed: () => _create(context, ref),
            icon: const Icon(Icons.add, size: 18),
            label: const Text('Create API key'),
          ),
        ),
      ],
    );
  }
}

// ------------------------------------------------------------------ SERVER

class _ServerSection extends ConsumerWidget {
  const _ServerSection();

  Future<void> _changeServer(BuildContext context, WidgetRef ref) async {
    final ok = await _confirm(
      context,
      'Change server?',
      'You will be signed out and asked for a new server address.',
      action: 'Change',
    );
    if (!ok || !context.mounted) return;
    await ref.read(authProvider.notifier).changeServer();
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final baseUrl = ref.watch(apiClientProvider).baseUrl;

    return _Section(
      title: 'SERVER',
      children: [
        ListTile(
          contentPadding: const EdgeInsets.symmetric(horizontal: 4),
          title: const Text('Server URL', style: TextStyle(fontSize: 14)),
          subtitle: Text(baseUrl,
              style: monoStyle.copyWith(color: NurbyColors.foreground)),
        ),
        Align(
          alignment: Alignment.centerLeft,
          child: OutlinedButton.icon(
            onPressed: () => _changeServer(context, ref),
            icon: const Icon(Icons.swap_horiz, size: 18),
            label: const Text('Change server'),
          ),
        ),
      ],
    );
  }
}
