import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../models/models.dart';
import '../voice/camera_voice_section.dart';
import 'camera_summaries_section.dart';
import 'camera_zones_section.dart';
import 'config_tiles.dart';
import 'detection_models_editor.dart';
import 'personas_section.dart';
import 'phone_mic_screen.dart';
import 'live_view.dart';

final _cameraProvider = FutureProvider.family<Camera, String>(
    (ref, id) => ref.watch(cameraRepoProvider).get(id));

/// AI providers, for the per-camera provider pickers. Cached once rather
/// than fetched per picker.
final _providersProvider = FutureProvider<List<Map<String, dynamic>>>(
    (ref) async => ((await ref.watch(apiClientProvider).getJson('/api/providers'))
            as List)
        .whereType<Map>()
        .map((p) => p.cast<String, dynamic>())
        .toList());

final _cameraActivityProvider = FutureProvider.family<List<Observation>, String>(
    (ref, id) => ref.watch(observationRepoProvider).list(cameraId: id, limit: 30));

/// Camera detail: live view, PTZ, config toggles, recent activity.
class CameraDetailScreen extends ConsumerWidget {
  const CameraDetailScreen({super.key, required this.cameraId});

  final String cameraId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final cameraAsync = ref.watch(_cameraProvider(cameraId));

    return cameraAsync.when(
      loading: () => Scaffold(
        appBar: AppBar(),
        body: const Center(child: CircularProgressIndicator()),
      ),
      error: (e, _) => Scaffold(
        appBar: AppBar(),
        body: Center(child: Text(apiErrorMessage(e))),
      ),
      data: (camera) => _CameraDetailBody(camera: camera),
    );
  }
}

class _CameraDetailBody extends ConsumerStatefulWidget {
  const _CameraDetailBody({required this.camera});
  final Camera camera;

  @override
  ConsumerState<_CameraDetailBody> createState() => _CameraDetailBodyState();
}

class _CameraDetailBodyState extends ConsumerState<_CameraDetailBody> {
  bool _saving = false;

  Future<void> _patch(Map<String, dynamic> patch) async {
    setState(() => _saving = true);
    try {
      await ref.read(cameraRepoProvider).update(widget.camera.id, patch);
      ref.invalidate(_cameraProvider(widget.camera.id));
      ref.invalidate(camerasProvider);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  /// Audio config has its own admin-only endpoint that writes an audit row
  /// per changed field. See CameraRepository.updateAudio.
  Future<void> _patchAudio(Map<String, dynamic> patch) async {
    setState(() => _saving = true);
    try {
      await ref.read(cameraRepoProvider).updateAudio(widget.camera.id, patch);
      ref.invalidate(_cameraProvider(widget.camera.id));
      ref.invalidate(camerasProvider);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  Future<void> _ptz(double pan, double tilt, double zoom) async {
    final api = ref.read(apiClientProvider);
    try {
      await api.postJson('/api/cameras/${widget.camera.id}/ptz/move',
          body: {'pan': pan, 'tilt': tilt, 'zoom': zoom});
      await Future<void>.delayed(const Duration(milliseconds: 400));
      await api.postJson('/api/cameras/${widget.camera.id}/ptz/stop');
    } catch (_) {
      // PTZ unsupported on this camera; ignore.
    }
  }

  Future<void> _delete() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: NurbyColors.cardElevated,
        title: const Text('Delete camera?'),
        content: Text(
            '"${widget.camera.name}" and its configuration will be removed.'),
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
      await ref.read(cameraRepoProvider).remove(widget.camera.id);
      ref.invalidate(camerasProvider);
      if (mounted) Navigator.pop(context);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final camera = widget.camera;
    final raw = camera.raw;
    final activity = ref.watch(_cameraActivityProvider(camera.id));
    final isRtsp = camera.streamType == 'rtsp';
    // Every camera config endpoint is admin-only server-side. Showing a
    // live control to someone who will only ever get a 403 is worse than
    // showing them the current value read-only.
    final isAdmin = ref.watch(authProvider).user?.isAdmin ?? false;
    final providers = ref.watch(_providersProvider).value ?? const [];

    return Scaffold(
      appBar: AppBar(
        title: Text(camera.name),
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
            ),
          PopupMenuButton<String>(
            color: NurbyColors.cardElevated,
            onSelected: (v) {
              if (v == 'delete') _delete();
              if (v == 'mic') {
                Navigator.of(context).push(MaterialPageRoute<void>(
                  builder: (_) => PhoneMicScreen(
                      cameraId: camera.id, cameraName: camera.name),
                ));
              }
            },
            itemBuilder: (_) => [
              // Only offered where it works: the mic session feeds the
              // AudioWorker of an audio_only camera whose stream_url is
              // the session's tcp port. Offering it on a normal camera
              // would look like it worked and go nowhere.
              if (raw['audio_only'] == true)
                const PopupMenuItem(
                  value: 'mic',
                  child: Text('Use this phone as its microphone'),
                ),
              const PopupMenuItem(
                value: 'delete',
                child: Text('Delete camera',
                    style: TextStyle(color: NurbyColors.danger)),
              ),
            ],
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(12),
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(12),
            child: AspectRatio(
              aspectRatio: 16 / 9,
              child: CameraLiveView(camera: camera),
            ),
          ),
          if (isRtsp) ...[
            const SizedBox(height: 10),
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                _ptzButton(Icons.chevron_left, () => _ptz(-0.5, 0, 0)),
                _ptzButton(Icons.chevron_right, () => _ptz(0.5, 0, 0)),
                _ptzButton(Icons.keyboard_arrow_up, () => _ptz(0, 0.5, 0)),
                _ptzButton(Icons.keyboard_arrow_down, () => _ptz(0, -0.5, 0)),
                _ptzButton(Icons.add, () => _ptz(0, 0, 0.5)),
                _ptzButton(Icons.remove, () => _ptz(0, 0, -0.5)),
              ],
            ),
          ],
          PersonasSection(
            cameraId: camera.id,
            cameraName: camera.name,
            isAdmin: isAdmin,
            sectionLabel: _sectionLabel,
            onPatch: _patch,
            onPatchAudio: _patchAudio,
          ),
          _sectionLabel('DETECTION'),
          Card(
            child: Column(children: [
              SwitchListTile(
                title: const Text('Object detection'),
                subtitle: Text(
                  (raw['detect_classes'] as List?)?.join(', ') ?? 'all classes',
                  style: const TextStyle(
                      color: NurbyColors.mutedForeground, fontSize: 12),
                ),
                value: camera.detectObjects,
                activeColor: NurbyColors.accent,
                onChanged: (v) => _patch({'detect_objects': v}),
              ),
              SwitchListTile(
                title: const Text('Face recognition'),
                value: camera.detectFaces,
                activeColor: NurbyColors.accent,
                onChanged: (v) => _patch({'detect_faces': v}),
              ),
              SwitchListTile(
                title: const Text('License plates'),
                value: raw['detect_plates'] as bool? ?? false,
                activeColor: NurbyColors.accent,
                onChanged: (v) => _patch({'detect_plates': v}),
              ),
            ]),
          ),
          _sectionLabel('RECORDING'),
          Card(
            child: SwitchListTile(
              title: const Text('Recording'),
              subtitle: Text(
                'mode: ${raw['recording_mode'] ?? 'objects'}',
                style: const TextStyle(
                    color: NurbyColors.mutedForeground, fontSize: 12),
              ),
              value: camera.recordingEnabled,
              activeColor: NurbyColors.accent,
              onChanged: isAdmin ? (v) => _patch({'recording_enabled': v}) : null,
            ),
          ),
          ..._detectionSection(raw, isAdmin),
          ..._aiSection(raw, isAdmin, providers),
          ..._refinerSection(raw, isAdmin, providers),
          ..._openVocabSection(raw, isAdmin),
          ..._summarySection(raw, isAdmin, providers),
          CameraZonesSection(
            cameraId: camera.id,
            raw: raw,
            isAdmin: isAdmin,
            sectionLabel: _sectionLabel,
            onPatch: _patch,
          ),
          CameraSummariesSection(
              cameraId: camera.id, sectionLabel: _sectionLabel),
          if (isAdmin)
            CameraVoiceSection(
                cameraId: camera.id, sectionLabel: _sectionLabel),
          ..._audioSection(raw, isAdmin),
          ..._conversationSection(raw, isAdmin),
          ..._incidentSection(raw, isAdmin),
          ..._digestSection(raw, isAdmin),
          _sectionLabel('RECENT ACTIVITY'),
          activity.when(
            loading: () => const Padding(
              padding: EdgeInsets.all(24),
              child: Center(child: CircularProgressIndicator()),
            ),
            error: (e, _) => Padding(
              padding: const EdgeInsets.all(12),
              child: Text(apiErrorMessage(e),
                  style: const TextStyle(color: NurbyColors.mutedForeground)),
            ),
            data: (obs) => obs.isEmpty
                ? const Padding(
                    padding: EdgeInsets.all(12),
                    child: Text('No recent activity',
                        style: TextStyle(color: NurbyColors.mutedForeground)),
                  )
                : Column(
                    children: [
                      for (final o in obs.take(15))
                        Card(
                          margin: const EdgeInsets.only(bottom: 8),
                          child: ListTile(
                            leading: o.thumbnailPath != null
                                ? ClipRRect(
                                    borderRadius: BorderRadius.circular(6),
                                    child: Image.network(
                                      ref
                                          .read(observationRepoProvider)
                                          .thumbnailUrl(o.id),
                                      width: 64,
                                      height: 44,
                                      fit: BoxFit.cover,
                                      errorBuilder: (_, __, ___) =>
                                          const SizedBox(width: 64),
                                    ),
                                  )
                                : null,
                            title: Text(
                              o.vlmDescription ?? o.labels.join(', '),
                              maxLines: 2,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(fontSize: 13),
                            ),
                            subtitle: Text(
                                DateFormat('MMM d, HH:mm').format(o.startedAt),
                                style: monoStyle),
                          ),
                        ),
                    ],
                  ),
          ),
        ],
      ),
    );
  }

  // ---------------------------------------------------------------------
  // Audio, conversations, incidents and digests (issue #161).
  //
  // These four sections are what turn the Incidents, Conversations and
  // Digests screens from empty lists into working ones. Each of those
  // screens renders data that only exists when the matching per-camera
  // toggle is on, and until now none of those toggles were reachable
  // from a phone at all.
  // ---------------------------------------------------------------------

  /// A list field off the raw camera JSON. These come back as null when
  /// unset rather than as an empty list.
  List<String> _strings(Map<String, dynamic> raw, String key) =>
      (raw[key] as List? ?? const []).map((e) => e.toString()).toList();

  List<Widget> _detectionSection(Map<String, dynamic> raw, bool isAdmin) {
    return [
      _sectionLabel('DETECTION TUNING'),
      Card(
        child: Column(children: [
          ConfigStringList(
            title: 'Classes to detect',
            values: _strings(raw, 'detect_classes'),
            // Empty means every class the model knows, not "detect
            // nothing". Getting that backwards in the UI would read as a
            // camera that has been switched off.
            placeholder: 'all classes',
            inputHint: 'person, car, dog',
            enabled: isAdmin,
            onChanged: (v) => _patch({'detect_classes': v}),
          ),
          Builder(builder: (context) {
            final models = (raw['detection_models'] as List? ?? const [])
                .whereType<Map>()
                .map((m) => m.cast<String, dynamic>())
                .toList();
            return ListTile(
              title: const Text('Models'),
              subtitle: Text(
                models.isEmpty
                    ? 'Default (YOLOv8 N)'
                    : models
                        .map((m) => modelLabel(m['model'] as String? ?? '') +
                            (m['enabled'] == false ? ' (off)' : ''))
                        .join(', '),
                style: const TextStyle(
                    color: NurbyColors.mutedForeground, fontSize: 12),
              ),
              trailing: isAdmin
                  ? const Icon(Icons.chevron_right,
                      size: 20, color: NurbyColors.mutedForeground)
                  : null,
              enabled: isAdmin,
              onTap: isAdmin
                  ? () => showModalBottomSheet<void>(
                        context: context,
                        isScrollControlled: true,
                        backgroundColor: NurbyColors.cardElevated,
                        builder: (_) => DetectionModelsEditor(
                          initial: models,
                          onSave: (next) => _patch({'detection_models': next}),
                        ),
                      )
                  : null,
            );
          }),
          ConfigChoice<String>(
            title: 'When models disagree',
            value: raw['detection_merge'] as String? ?? 'any',
            options: const ['any', 'consensus', 'best'],
            labels: const {
              'any': 'Any model is enough',
              'consensus': 'Several must agree',
              'best': 'Trust the highest score',
            },
            hints: const {
              'any': 'Most sensitive. More detections, more false ones.',
              'consensus': 'Fewest false alarms, may miss brief events.',
              'best': 'One detection, from whichever model was surest.',
            },
            enabled: isAdmin,
            onChanged: (v) => _patch({'detection_merge': v}),
          ),
          ConfigNumber(
            title: 'Models that must agree',
            value: raw['detection_consensus_min'] as int? ?? 2,
            min: 1,
            max: 10,
            suffix: 'models',
            hint: 'only used in consensus mode',
            enabled: isAdmin && raw['detection_merge'] == 'consensus',
            onChanged: (v) => _patch({'detection_consensus_min': v}),
          ),
        ]),
      ),
    ];
  }

  List<Widget> _aiSection(Map<String, dynamic> raw, bool isAdmin,
      List<Map<String, dynamic>> providers) {
    final onObject = raw['vlm_trigger'] == 'on_object';
    return [
      _sectionLabel('AI ANALYSIS'),
      Card(
        child: Column(children: [
          ConfigText(
            title: 'What to look for',
            value: raw['vlm_prompt'] as String?,
            placeholder: 'default',
            hintText: 'Describe what to watch for',
            maxLength: 4096,
            enabled: isAdmin,
            onChanged: (v) => _patch({'vlm_prompt': v}),
          ),
          ConfigProvider(
            title: 'Model',
            value: raw['vlm_provider_id'] as String?,
            providers: providers,
            enabled: isAdmin,
            onChanged: (v) => _patch({'vlm_provider_id': v}),
          ),
          ConfigChoice<String>(
            title: 'When to look',
            value: raw['vlm_trigger'] as String? ?? 'always',
            options: const ['always', 'on_object'],
            labels: const {
              'always': 'Every frame it samples',
              'on_object': 'Only when something is detected',
            },
            enabled: isAdmin,
            onChanged: (v) => _patch({'vlm_trigger': v}),
          ),
          ConfigStringList(
            title: 'Objects that trigger analysis',
            values: _strings(raw, 'vlm_trigger_objects'),
            placeholder: 'anything detected',
            inputHint: 'person, package',
            enabled: isAdmin && onObject,
            onChanged: (v) => _patch({'vlm_trigger_objects': v}),
          ),
          ConfigNumber(
            title: 'Minimum gap between looks',
            value: raw['vlm_interval'] as int? ?? 0,
            min: 0,
            max: 3600,
            suffix: 'seconds',
            hint: '0 means no limit',
            enabled: isAdmin,
            onChanged: (v) => _patch({'vlm_interval': v}),
          ),
          ConfigNumber(
            title: 'Description length',
            value: raw['vlm_max_tokens'] as int? ?? 400,
            min: 50,
            max: 2000,
            suffix: 'tokens',
            hint: '400 fits two to four sentences',
            enabled: isAdmin,
            onChanged: (v) => _patch({'vlm_max_tokens': v}),
          ),
          ConfigNumber(
            title: 'Input budget',
            value: raw['vlm_max_input_tokens'] as int? ?? 4096,
            min: 64,
            max: 2000000,
            suffix: 'tokens',
            enabled: isAdmin,
            onChanged: (v) => _patch({'vlm_max_input_tokens': v}),
          ),
        ]),
      ),
    ];
  }

  List<Widget> _refinerSection(Map<String, dynamic> raw, bool isAdmin,
      List<Map<String, dynamic>> providers) {
    // The refiner is a second, usually better model that re-reads an
    // observation the first pass found interesting. Off unless a provider
    // is set, so everything below follows that.
    final on = raw['vlm_refiner_provider_id'] != null;
    return [
      _sectionLabel('SECOND LOOK'),
      Card(
        child: Column(children: [
          ConfigProvider(
            title: 'Refiner model',
            value: raw['vlm_refiner_provider_id'] as String?,
            providers: providers,
            enabled: isAdmin,
            onChanged: (v) => _patch({'vlm_refiner_provider_id': v}),
          ),
          ConfigStringList(
            title: 'Words worth a second look',
            values: _strings(raw, 'vlm_refiner_keywords'),
            placeholder: 'none',
            inputHint: 'package, ladder',
            enabled: isAdmin && on,
            onChanged: (v) => _patch({'vlm_refiner_keywords': v}),
          ),
          ConfigStringList(
            title: 'Objects worth a second look',
            values: _strings(raw, 'vlm_refiner_trigger_objects'),
            placeholder: 'none',
            inputHint: 'person',
            enabled: isAdmin && on,
            onChanged: (v) => _patch({'vlm_refiner_trigger_objects': v}),
          ),
          ConfigNumber(
            title: 'Description length',
            value: raw['vlm_refiner_max_tokens'] as int? ?? 400,
            min: 50,
            max: 2000,
            suffix: 'tokens',
            enabled: isAdmin && on,
            onChanged: (v) => _patch({'vlm_refiner_max_tokens': v}),
          ),
          ConfigNumber(
            title: 'Input budget',
            value: raw['vlm_refiner_max_input_tokens'] as int? ?? 4096,
            min: 64,
            max: 2000000,
            suffix: 'tokens',
            enabled: isAdmin && on,
            onChanged: (v) => _patch({'vlm_refiner_max_input_tokens': v}),
          ),
        ]),
      ),
    ];
  }

  List<Widget> _openVocabSection(Map<String, dynamic> raw, bool isAdmin) {
    return [
      _sectionLabel('OPEN VOCABULARY'),
      Card(
        child: Column(children: [
          ConfigStringList(
            title: 'Things to watch for',
            values: _strings(raw, 'yolo_world_prompts'),
            placeholder: 'none',
            hint: 'described in words, not model classes',
            inputHint: 'a person carrying a ladder',
            enabled: isAdmin,
            onChanged: (v) => _patch({'yolo_world_prompts': v}),
          ),
        ]),
      ),
    ];
  }

  List<Widget> _summarySection(Map<String, dynamic> raw, bool isAdmin,
      List<Map<String, dynamic>> providers) {
    final mode = raw['summary_mode'] as String? ?? 'off';
    final periodic = mode == 'periodic' || mode == 'both';
    final onEvent = mode == 'event' || mode == 'both';
    return [
      _sectionLabel('SUMMARIES'),
      Card(
        child: Column(children: [
          ConfigChoice<String>(
            title: 'Write summaries',
            value: mode,
            options: const ['off', 'periodic', 'event', 'both'],
            labels: const {
              'off': 'Off',
              'periodic': 'On a clock',
              'event': 'After something happens',
              'both': 'Both',
            },
            enabled: isAdmin,
            onChanged: (v) => _patch({'summary_mode': v}),
          ),
          ConfigProvider(
            title: 'Summary model',
            value: raw['summary_provider_id'] as String?,
            providers: providers,
            enabled: isAdmin && mode != 'off',
            onChanged: (v) => _patch({'summary_provider_id': v}),
          ),
          ConfigNumber(
            title: 'How often',
            value: raw['summary_period_seconds'] as int? ?? 1800,
            min: 60,
            max: 86400,
            suffix: 'seconds',
            enabled: isAdmin && periodic,
            onChanged: (v) => _patch({'summary_period_seconds': v}),
          ),
          ConfigNumber(
            title: 'Quiet before summarising',
            value: raw['summary_event_quiet_seconds'] as int? ?? 60,
            min: 5,
            max: 3600,
            suffix: 'seconds',
            hint: 'wait for the event to finish',
            enabled: isAdmin && onEvent,
            onChanged: (v) => _patch({'summary_event_quiet_seconds': v}),
          ),
          ConfigNumber(
            title: 'Ignore events shorter than',
            value: raw['summary_event_min_duration_seconds'] as int? ?? 5,
            min: 1,
            max: 3600,
            suffix: 'seconds',
            enabled: isAdmin && onEvent,
            onChanged: (v) =>
                _patch({'summary_event_min_duration_seconds': v}),
          ),
          ConfigStringList(
            title: 'Objects that trigger a summary',
            values: _strings(raw, 'summary_event_trigger_objects'),
            placeholder: 'anything',
            inputHint: 'person, car',
            enabled: isAdmin && onEvent,
            onChanged: (v) => _patch({'summary_event_trigger_objects': v}),
          ),
          ConfigNumber(
            title: 'Summary length',
            value: raw['summary_max_tokens'] as int? ?? 400,
            min: 50,
            max: 2000,
            suffix: 'tokens',
            enabled: isAdmin && mode != 'off',
            onChanged: (v) => _patch({'summary_max_tokens': v}),
          ),
        ]),
      ),
    ];
  }

  List<Widget> _audioSection(Map<String, dynamic> raw, bool isAdmin) {
    final capture = raw['audio_capture_enabled'] as bool? ?? false;
    return [
      _sectionLabel('AUDIO'),
      Card(
        child: Column(children: [
          ConfigSwitch(
            title: 'Capture audio',
            subtitle: 'Pulls the audio track from this camera. '
                'Required before any transcription.',
            value: capture,
            enabled: isAdmin,
            onChanged: (v) => _patchAudio({'audio_capture_enabled': v}),
          ),
          ConfigSwitch(
            title: 'Transcribe speech',
            subtitle: 'Runs speech-to-text against captured audio.',
            value: raw['audio_transcribe_enabled'] as bool? ?? false,
            // Transcription without capture is not a valid state. Greying
            // it out says which switch to reach for first.
            enabled: isAdmin && capture,
            onChanged: (v) => _patchAudio({'audio_transcribe_enabled': v}),
          ),
          ConfigSwitch(
            title: 'Store raw audio',
            subtitle: 'Keeps encoded clips on disk for playback. '
                'Off means transcripts only.',
            value: raw['audio_store_raw'] as bool? ?? false,
            enabled: isAdmin && capture,
            onChanged: (v) => _patchAudio({'audio_store_raw': v}),
          ),
          ConfigChoice<String>(
            title: 'Transcript storage',
            value: raw['transcript_store'] as String? ?? 'full',
            options: const ['full', 'redacted', 'summary_only', 'off'],
            labels: const {
              'full': 'Full text',
              'redacted': 'Redacted',
              'summary_only': 'Summary only',
              'off': 'Off (live only)',
            },
            enabled: isAdmin,
            onChanged: (v) => _patchAudio({'transcript_store': v}),
          ),
          ConfigChoice<String>(
            title: 'Spoken language',
            value: raw['audio_language'] as String? ?? 'en',
            options: _languages,
            labels: _languageNames,
            enabled: isAdmin,
            onChanged: (v) => _patchAudio({'audio_language': v}),
          ),
          ConfigNumber(
            title: 'Audio retention',
            value: raw['audio_retention_days'] as int? ?? 7,
            min: 0,
            max: 3650,
            suffix: 'days',
            hint: '0 keeps nothing',
            enabled: isAdmin,
            onChanged: (v) => _patchAudio({'audio_retention_days': v}),
          ),
          ConfigNumber(
            title: 'Transcript retention',
            value: raw['transcript_retention_days'] as int? ?? 30,
            min: 0,
            max: 3650,
            suffix: 'days',
            enabled: isAdmin,
            onChanged: (v) => _patchAudio({'transcript_retention_days': v}),
          ),
          ConfigNumber(
            title: 'Transcription budget',
            value: raw['stt_budget_minutes_per_hour'] as int? ?? 30,
            min: 0,
            max: 600,
            suffix: 'min/hour',
            enabled: isAdmin,
            onChanged: (v) => _patchAudio({'stt_budget_minutes_per_hour': v}),
          ),
          ConfigNumber(
            title: 'Decoding quality',
            value: raw['audio_stt_beam_size'] as int? ?? 1,
            min: 1,
            max: 10,
            hint: 'beam size, higher is slower',
            enabled: isAdmin,
            onChanged: (v) => _patchAudio({'audio_stt_beam_size': v}),
          ),
          ConfigSwitch(
            title: 'Carry context across segments',
            subtitle: 'More coherent long speech, but one transcription '
                'error can carry into the next segment.',
            value:
                raw['audio_stt_condition_on_previous_text'] as bool? ?? false,
            enabled: isAdmin,
            onChanged: (v) =>
                _patchAudio({'audio_stt_condition_on_previous_text': v}),
          ),
          ConfigChoice<double>(
            title: 'Silence threshold',
            value: (raw['audio_stt_no_speech_threshold'] as num?)?.toDouble() ??
                0.6,
            options: const [0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
            // Not const: Dart rejects double keys in a const map.
            labels: {
              0.3: '0.3 (transcribes more)',
              0.4: '0.4',
              0.5: '0.5',
              0.6: '0.6 (default)',
              0.7: '0.7',
              0.8: '0.8 (drops more)',
            },
            enabled: isAdmin,
            onChanged: (v) =>
                _patchAudio({'audio_stt_no_speech_threshold': v}),
          ),
        ]),
      ),
    ];
  }

  List<Widget> _conversationSection(Map<String, dynamic> raw, bool isAdmin) {
    return [
      _sectionLabel('CONVERSATIONS'),
      Card(
        child: Column(children: [
          ConfigNumber(
            title: 'Gap between conversations',
            value: raw['conversation_gap_seconds'] as int? ?? 30,
            min: 5,
            max: 600,
            suffix: 'seconds',
            hint: 'silence longer than this starts a new one',
            enabled: isAdmin,
            onChanged: (v) => _patch({'conversation_gap_seconds': v}),
          ),
          ConfigSwitch(
            title: 'Summarize conversations',
            value: raw['conversation_summary_enabled'] as bool? ?? true,
            enabled: isAdmin,
            onChanged: (v) => _patch({'conversation_summary_enabled': v}),
          ),
          ConfigNumber(
            title: 'Minimum lines to summarize',
            value: raw['conversation_min_messages_for_summary'] as int? ?? 2,
            min: 1,
            max: 20,
            suffix: 'lines',
            enabled: isAdmin,
            onChanged: (v) =>
                _patch({'conversation_min_messages_for_summary': v}),
          ),
        ]),
      ),
    ];
  }

  List<Widget> _incidentSection(Map<String, dynamic> raw, bool isAdmin) {
    return [
      _sectionLabel('INCIDENT TRACKING'),
      Card(
        child: Column(children: [
          ConfigSwitch(
            title: 'Group repeat sightings',
            subtitle: 'Folds repeated sightings of the same subject into '
                'one incident instead of many separate events.',
            value: raw['incident_tracking_enabled'] as bool? ?? true,
            enabled: isAdmin,
            onChanged: (v) => _patch({'incident_tracking_enabled': v}),
          ),
          ConfigNumber(
            title: 'Close an incident after',
            value: raw['incident_idle_seconds'] as int? ?? 600,
            min: 30,
            max: 86400,
            suffix: 'seconds',
            hint: 'idle time before the subject counts as gone',
            enabled: isAdmin,
            onChanged: (v) => _patch({'incident_idle_seconds': v}),
          ),
        ]),
      ),
    ];
  }

  List<Widget> _digestSection(Map<String, dynamic> raw, bool isAdmin) {
    return [
      _sectionLabel('ACTIVITY DIGEST'),
      Card(
        child: Column(children: [
          ConfigSwitch(
            title: 'Write periodic digests',
            value: raw['digest_enabled'] as bool? ?? true,
            enabled: isAdmin,
            onChanged: (v) => _patch({'digest_enabled': v}),
          ),
          ConfigChoice<String>(
            title: 'Digest period',
            value: raw['digest_period'] as String? ?? '24h',
            options: const ['1h', '6h', '12h', '24h', '48h', '7d'],
            labels: const {
              '1h': 'Every hour',
              '6h': 'Every 6 hours',
              '12h': 'Every 12 hours',
              '24h': 'Daily',
              '48h': 'Every 2 days',
              '7d': 'Weekly',
            },
            enabled: isAdmin,
            onChanged: (v) => _patch({'digest_period': v}),
          ),
          ConfigText(
            title: 'Digest prompt',
            value: raw['digest_prompt'] as String?,
            hintText: 'What should the digest pay attention to?',
            maxLength: 4096,
            enabled: isAdmin,
            onChanged: (v) => _patch({'digest_prompt': v}),
          ),
        ]),
      ),
    ];
  }

  Widget _ptzButton(IconData icon, VoidCallback onTap) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 4),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(10),
        child: Container(
          width: 44,
          height: 44,
          decoration: BoxDecoration(
            color: NurbyColors.card,
            border: Border.all(color: NurbyColors.border),
            borderRadius: BorderRadius.circular(10),
          ),
          child: Icon(icon, size: 20, color: NurbyColors.mutedForeground),
        ),
      ),
    );
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

const _languages = [
  'auto', 'en', 'es', 'fr', 'de', 'it', 'pt', 'nl', 'pl',
  'ru', 'tr', 'ar', 'hi', 'bn', 'ja', 'ko', 'zh',
];

const _languageNames = {
  'auto': 'Auto-detect',
  'en': 'English',
  'es': 'Spanish',
  'fr': 'French',
  'de': 'German',
  'it': 'Italian',
  'pt': 'Portuguese',
  'nl': 'Dutch',
  'pl': 'Polish',
  'ru': 'Russian',
  'tr': 'Turkish',
  'ar': 'Arabic',
  'hi': 'Hindi',
  'bn': 'Bengali',
  'ja': 'Japanese',
  'ko': 'Korean',
  'zh': 'Chinese',
};
