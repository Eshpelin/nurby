import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../cameras/config_tiles.dart';

/// One camera's voice configuration (issue #159).
///
/// Shown inside camera detail. The preset is inferred by the server from
/// the camera's actual numbers rather than stored, so a camera whose
/// volume was nudged by hand reads as Custom instead of continuing to
/// claim a preset it no longer matches.
final cameraVoiceProvider =
    FutureProvider.family<Map<String, dynamic>, String>(
        (ref, cameraId) => ref.watch(voiceRepoProvider).camera(cameraId));

final voicePresetsProvider = FutureProvider<List<Map<String, dynamic>>>(
    (ref) => ref.watch(voiceRepoProvider).presets());

class CameraVoiceSection extends ConsumerStatefulWidget {
  const CameraVoiceSection({
    super.key,
    required this.cameraId,
    required this.sectionLabel,
  });

  final String cameraId;

  /// The camera page's own section-heading builder, passed in so this
  /// block looks like every other section rather than importing the
  /// screen it is embedded in.
  final Widget Function(String) sectionLabel;

  @override
  ConsumerState<CameraVoiceSection> createState() =>
      _CameraVoiceSectionState();
}

class _CameraVoiceSectionState extends ConsumerState<CameraVoiceSection> {
  bool _busy = false;

  Future<void> _patch(Map<String, dynamic> patch) async {
    setState(() => _busy = true);
    try {
      await ref.read(voiceRepoProvider).updateCamera(widget.cameraId, patch);
      ref.invalidate(cameraVoiceProvider(widget.cameraId));
    } catch (e) {
      _toast(apiErrorMessage(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _test() async {
    setState(() => _busy = true);
    try {
      final r = await ref.read(voiceRepoProvider).test(widget.cameraId);
      // A refusal is a real answer, not a failure. The test runs through
      // the same guards as everything else, so "not played, quiet hours"
      // is the honest result and worth showing plainly.
      _toast(r['spoken'] == true
          ? 'Played over ${r['transport'] ?? 'the speaker'}.'
          : 'Not played: ${r['reason'] ?? r['status'] ?? 'unknown'}');
    } catch (e) {
      _toast(apiErrorMessage(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _toast(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(cameraVoiceProvider(widget.cameraId));

    return async.when(
      // Voice config is admin-only and not every camera has a speaker.
      // Neither case is worth an error banner on the camera page, so the
      // section simply is not there.
      loading: () => const SizedBox.shrink(),
      error: (_, __) => const SizedBox.shrink(),
      data: (v) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          widget.sectionLabel('VOICE'),
          Card(child: _body(v)),
        ],
      ),
    );
  }

  Widget _body(Map<String, dynamic> v) {
    final capability = (v['capability'] as Map?)?.cast<String, dynamic>() ??
        const <String, dynamic>{};
    final probed = capability['probed'] == true;
    final supported = capability['supported'] == true;
    final enabled = v['speaker_enabled'] as bool? ?? false;
    final presets = ref.watch(voicePresetsProvider).value ?? const [];

    return Column(
      children: [
        // Three states, and they mean different things: never probed is
        // not the same as probed and unsupported. A household should not
        // conclude their camera is mute when nobody ever checked.
        ListTile(
          leading: Icon(
            probed
                ? (supported ? Icons.volume_up : Icons.volume_off)
                : Icons.help_outline,
            color: probed
                ? (supported ? NurbyColors.accent : NurbyColors.mutedForeground)
                : NurbyColors.warning,
          ),
          title: Text('${capability['summary'] ?? 'Speaker state unknown'}',
              style: const TextStyle(fontSize: 13)),
          subtitle: probed && supported && capability['codec'] != null
              ? Text('${capability['codec']} · ${capability['sample_rate']} Hz',
                  style: _sub)
              : null,
          trailing: _busy
              ? const SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(strokeWidth: 2))
              : null,
        ),
        ConfigSwitch(
          title: 'Speak through this camera',
          value: enabled,
          // Enabling a camera the probe says cannot play audio would
          // produce a setting that silently never fires.
          enabled: !probed || supported,
          onChanged: (b) => _patch({'speaker_enabled': b}),
        ),
        if (presets.isNotEmpty)
          ConfigChoice<String>(
            title: 'Policy',
            value: v['preset'] as String? ?? 'custom',
            options: [for (final p in presets) p['key'] as String],
            labels: {
              for (final p in presets) p['key'] as String: p['label'] as String
            },
            hints: {
              for (final p in presets)
                p['key'] as String: p['description'] as String
            },
            enabled: enabled,
            onChanged: (key) => _patch({'preset': key}),
          ),
        ConfigText(
          title: 'Voice',
          value: v['speaker_voice'] as String?,
          placeholder: 'household default',
          hintText: 'Voice name from your speech engine',
          maxLines: 1,
          enabled: enabled,
          onChanged: (val) => _patch({'speaker_voice': val}),
        ),

        // The server only requires >= 0 on these two. The upper bounds
        // are the app's own: a cooldown longer than a day, or more than
        // ten thousand announcements in one, are not settings anyone
        // means. Do not "correct" them to match the server.

        AdvancedFold(children: [
        ConfigNumber(
          title: 'Volume',
          value: v['speaker_volume'] as int? ?? 70,
          min: 1,
          max: 100,
          enabled: enabled,
          onChanged: (val) => _patch({'speaker_volume': val}),
        ),
        ConfigNumber(
          title: 'Wait between announcements',
          value: v['speaker_cooldown_seconds'] as int? ?? 30,
          min: 0,
          max: 86400,
          suffix: 'seconds',
          enabled: enabled,
          onChanged: (val) => _patch({'speaker_cooldown_seconds': val}),
        ),

        ConfigNumber(
          title: 'Daily cap',
          value: v['speaker_daily_cap'] as int? ?? 50,
          min: 0,
          max: 10000,
          suffix: 'per day',
          hint: '0 means never',
          enabled: enabled,
          onChanged: (val) => _patch({'speaker_daily_cap': val}),
        ),
        ]),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 12),
          child: Row(
            children: [
              OutlinedButton.icon(
                onPressed: _busy || !enabled ? null : _test,
                icon: const Icon(Icons.campaign_outlined, size: 18),
                label: const Text('Say a test phrase'),
              ),
              const SizedBox(width: 10),
              const Expanded(
                child: Text(
                  'Runs through the real guards, so it can refuse during '
                  'quiet hours.',
                  style: _sub,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

const _sub = TextStyle(color: NurbyColors.mutedForeground, fontSize: 12);
