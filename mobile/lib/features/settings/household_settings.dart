import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../cameras/config_tiles.dart';

/// Household-wide settings with real names (issue #169).
///
/// Mobile already had a generic editor that listed every system setting
/// by its raw key, with a free-text dialog and no bounds. That made
/// "nudity_blur" and "journey_idle_seconds" technically reachable and
/// practically unusable. This section gives the keys people actually
/// touch a label, a sentence, and a control that knows its limits. The
/// generic list stays for everything else, minus these, so nothing
/// appears twice.
final householdSettingsProvider = FutureProvider<Map<String, dynamic>>(
    (ref) async =>
        (await ref.watch(apiClientProvider).getJson('/api/system/settings')
                as Map)
            .cast<String, dynamic>());

/// Keys this section owns. The generic editor hides them.
const kCuratedSettingKeys = {
  'nudity_blur',
  'detect_classes',
  'vlm_enrichment_enabled',
  'vlm_enrichment_budget_minutes_per_hour',
  'journey_idle_seconds',
  'daily_digest_enabled',
  'daily_digest_hour',
  'system_timezone',
  'audio_events',
};

class HouseholdSettingsSection extends ConsumerStatefulWidget {
  const HouseholdSettingsSection({super.key, required this.isAdmin});

  final bool isAdmin;

  @override
  ConsumerState<HouseholdSettingsSection> createState() =>
      _HouseholdSettingsSectionState();
}

class _HouseholdSettingsSectionState
    extends ConsumerState<HouseholdSettingsSection> {
  Future<void> _patch(Map<String, dynamic> patch) async {
    try {
      await ref
          .read(apiClientProvider)
          .patchJson('/api/system/settings', body: patch);
      ref.invalidate(householdSettingsProvider);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(householdSettingsProvider);
    final s = async.value;
    if (s == null) return const SizedBox.shrink();
    final isAdmin = widget.isAdmin;
    final enrich = s['vlm_enrichment_enabled'] as bool? ?? false;
    final digest = s['daily_digest_enabled'] as bool? ?? true;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _label('HOUSEHOLD'),
        Card(
          child: Column(children: [
            ConfigSwitch(
              title: 'Privacy blur',
              subtitle: 'Blurs nudity before a frame is stored or shown. '
                  'On by default and worth leaving on.',
              value: s['nudity_blur'] as bool? ?? true,
              enabled: isAdmin,
              onChanged: (v) => _patch({'nudity_blur': v}),
            ),
            ConfigStringList(
              title: 'Objects to detect',
              values: (s['detect_classes'] as List? ?? const [])
                  .map((e) => e.toString())
                  .toList(),
              // Null and empty both mean everything, and the server
              // stores null. Say "everything" rather than "none".
              placeholder: 'everything the model knows',
              hint: 'household default, cameras can narrow it',
              inputHint: 'person, car, dog',
              enabled: isAdmin,
              onChanged: (v) => _patch({'detect_classes': v.isEmpty ? null : v}),
            ),

            ConfigSwitch(
              title: 'Listen for sounds',
              subtitle: 'Glass breaking, a dog barking, a doorbell. '
                  'Separate from speech transcription.',
              value: s['audio_events'] as bool? ?? true,
              enabled: isAdmin,
              onChanged: (v) => _patch({'audio_events': v}),
            ),
            ConfigSwitch(
              title: 'Morning recap',
              subtitle: 'One household recap a day.',
              value: digest,
              enabled: isAdmin,
              onChanged: (v) => _patch({'daily_digest_enabled': v}),
            ),
            ConfigNumber(
              title: 'Recap hour',
              value: s['daily_digest_hour'] as int? ?? 7,
              min: 0,
              max: 23,
              hint: 'local time, 24 hour',
              enabled: isAdmin && digest,
              onChanged: (v) => _patch({'daily_digest_hour': v}),
            ),
            ConfigText(
              title: 'Household timezone',
              value: s['system_timezone'] as String?,
              placeholder: 'server default',
              hintText: 'Europe/London',
              maxLines: 1,
              enabled: isAdmin,
              onChanged: (v) => _patch({'system_timezone': v}),
            ),
          AdvancedFold(children: [
            ConfigSwitch(
              title: 'Describe scenes while idle',
              subtitle: 'Uses spare AI time to add descriptions to '
                  'sightings that did not get one.',
              value: enrich,
              enabled: isAdmin,
              onChanged: (v) => _patch({'vlm_enrichment_enabled': v}),
            ),

            ConfigNumber(
              title: 'Idle budget',
              value: s['vlm_enrichment_budget_minutes_per_hour'] as int? ?? 10,
              min: 0,
              max: 600,
              suffix: 'min/hour',
              enabled: isAdmin && enrich,
              onChanged: (v) =>
                  _patch({'vlm_enrichment_budget_minutes_per_hour': v}),
            ),

            ConfigNumber(
              title: 'End a journey after',
              value: s['journey_idle_seconds'] as int? ?? 300,
              min: 1,
              max: 86400,
              suffix: 'seconds',
              hint: 'unseen on every camera for this long',
              enabled: isAdmin,
              onChanged: (v) => _patch({'journey_idle_seconds': v}),
            ),
            ]),
          ]),
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------
// Local AI: one-click Ollama deploy.
// ---------------------------------------------------------------------

final ollamaStatusProvider = FutureProvider<Map<String, dynamic>>(
    (ref) async =>
        (await ref.watch(apiClientProvider).getJson('/api/ollama/status') as Map)
            .cast<String, dynamic>());

class LocalAiSection extends ConsumerStatefulWidget {
  const LocalAiSection({super.key});

  @override
  ConsumerState<LocalAiSection> createState() => _LocalAiSectionState();
}

class _LocalAiSectionState extends ConsumerState<LocalAiSection> {
  Timer? _poll;
  Map<String, dynamic>? _deploy;

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  Future<void> _start(String model) async {
    try {
      final r = await ref
          .read(apiClientProvider)
          .postJson('/api/ollama/deploy', body: {'model': model}) as Map;
      setState(() => _deploy = r.cast<String, dynamic>());
      // A pull takes minutes. Poll the job rather than hold a request
      // open, and stop the moment it reaches a terminal stage.
      _poll?.cancel();
      _poll = Timer.periodic(const Duration(seconds: 3), (_) => _tick());
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    }
  }

  Future<void> _tick() async {
    try {
      final r = (await ref
              .read(apiClientProvider)
              .getJson('/api/ollama/deploy/status') as Map)
          .cast<String, dynamic>();
      if (!mounted) return;
      setState(() => _deploy = r);
      if (_isTerminal(r['stage'] as String?)) {
        _poll?.cancel();
        ref.invalidate(ollamaStatusProvider);
      }
    } catch (_) {
      // Transient. The next tick will try again.
    }
  }

  Future<void> _cancel() async {
    try {
      await ref.read(apiClientProvider).delete('/api/ollama/deploy');
      _poll?.cancel();
      setState(() => _deploy = null);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    }
  }

  static bool _isTerminal(String? stage) =>
      stage == 'done' || stage == 'error' || stage == 'cancelled' || stage == null;

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(ollamaStatusProvider);
    final d = _deploy;
    final inFlight = d != null && !_isTerminal(d['stage'] as String?);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _label('LOCAL AI'),
        Card(
          child: async.when(
            loading: () => const ListTile(title: LinearProgressIndicator()),
            error: (e, _) => ListTile(
              title: const Text('Local AI'),
              subtitle: Text(apiErrorMessage(e), style: _sub),
            ),
            data: (s) {
              final installed = s['installed'] == true;
              final running = s['running'] == true;
              final models = (s['models'] as List? ?? const []);
              final ram = (s['system_ram_gb'] as num?)?.toStringAsFixed(0);
              final disk = (s['disk_free_gb'] as num?)?.toStringAsFixed(0);
              final catalogue = (s['available_models'] as List? ?? const [])
                  .whereType<Map>()
                  .map((m) => m.cast<String, dynamic>())
                  .toList();

              return Column(children: [
                ListTile(
                  leading: Icon(
                    running ? Icons.memory : Icons.memory_outlined,
                    color: running
                        ? NurbyColors.accent
                        : NurbyColors.mutedForeground,
                  ),
                  title: Text(
                    !installed
                        ? 'Ollama is not installed on the server'
                        : running
                            ? 'Ollama is running'
                            : 'Ollama is installed but not running',
                    style: const TextStyle(fontSize: 13),
                  ),
                  subtitle: Text(
                    [
                      if (models.isNotEmpty)
                        '${models.length} ${models.length == 1 ? 'model' : 'models'}',
                      if (ram != null) '$ram GB RAM',
                      if (disk != null) '$disk GB free',
                    ].join(' · '),
                    style: _sub,
                  ),
                ),
                if (inFlight) ...[
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        LinearProgressIndicator(
                          value: ((d['progress'] as num?)?.toDouble() ?? 0)
                              .clamp(0, 1),
                          color: NurbyColors.accent,
                        ),
                        const SizedBox(height: 6),
                        Text('${d['message'] ?? d['stage']}', style: _sub),
                      ],
                    ),
                  ),
                  Align(
                    alignment: Alignment.centerRight,
                    child: TextButton(
                        onPressed: _cancel, child: const Text('Cancel')),
                  ),
                ] else if (d != null && d['stage'] == 'error')
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
                    child: Text('${d['message'] ?? 'The deploy failed.'}',
                        style: const TextStyle(
                            fontSize: 12, color: NurbyColors.danger)),
                  )
                else if (running || installed)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
                    child: Wrap(
                      spacing: 6,
                      runSpacing: 6,
                      children: [
                        for (final m in catalogue.take(6))
                          ActionChip(
                            // The server says what fits this machine.
                            // A model that will not fit is still shown,
                            // greyed, so its absence is not a mystery.
                            label: Text(
                              '${m['label']} · ${m['ram_gb']} GB',
                              style: const TextStyle(fontSize: 11),
                            ),
                            onPressed: _fits(m, s)
                                ? () => _start(m['name'] as String)
                                : null,
                          ),
                      ],
                    ),
                  ),
              ]);
            },
          ),
        ),
      ],
    );
  }

  static bool _fits(Map<String, dynamic> m, Map<String, dynamic> status) {
    final ram = (status['system_ram_gb'] as num?)?.toDouble();
    final need = (m['ram_gb'] as num?)?.toDouble();
    if (ram == null || need == null) return true;
    return need <= ram;
  }
}

Widget _label(String text) => Padding(
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

const _sub = TextStyle(color: NurbyColors.mutedForeground, fontSize: 12);
