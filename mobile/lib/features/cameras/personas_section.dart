import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';

/// Quick personas (issue #160, deferred part).
///
/// One tap sets a bundle of settings for a common use-case: front door,
/// baby cam, driveway. The list comes from /api/cameras/personas so web
/// and mobile apply the same bundle; it used to be a TypeScript constant
/// and a Dart copy would have drifted the first time someone tuned one.
final personasProvider = FutureProvider<Map<String, dynamic>>((ref) async =>
    (await ref.watch(apiClientProvider).getJson('/api/cameras/personas') as Map)
        .cast<String, dynamic>());

/// Split a persona patch into what goes to the camera PATCH and what
/// goes to the audio endpoint, using the field list the server sent.
/// Pure.
({Map<String, dynamic> camera, Map<String, dynamic> audio}) splitPersonaPatch(
    Map<String, dynamic> patch, Iterable<String> audioFields) {
  final audio = audioFields.toSet();
  return (
    camera: {for (final e in patch.entries) if (!audio.contains(e.key)) e.key: e.value},
    audio: {for (final e in patch.entries) if (audio.contains(e.key)) e.key: e.value},
  );
}

class PersonasSection extends ConsumerStatefulWidget {
  const PersonasSection({
    super.key,
    required this.cameraId,
    required this.cameraName,
    required this.isAdmin,
    required this.sectionLabel,
    required this.onPatch,
    required this.onPatchAudio,
  });

  final String cameraId;
  final String cameraName;
  final bool isAdmin;
  final Widget Function(String) sectionLabel;
  final Future<void> Function(Map<String, dynamic>) onPatch;
  final Future<void> Function(Map<String, dynamic>) onPatchAudio;

  @override
  ConsumerState<PersonasSection> createState() => _PersonasSectionState();
}

class _PersonasSectionState extends ConsumerState<PersonasSection> {
  String? _applying;

  Future<void> _apply(Map<String, dynamic> persona, List<String> audioFields) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: NurbyColors.cardElevated,
        title: Text('Set up as ${persona['label']}?'),
        // A persona overwrites a specific set of fields. Saying which
        // fields is too much; saying that it overwrites, and that
        // everything stays editable afterwards, is the honest minimum.
        content: Text(
          '${persona['hint']}\n\nThis changes ${(persona['patch'] as Map).length} '
          'settings on ${widget.cameraName}. You can adjust any of them '
          'afterwards.',
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Cancel')),
          FilledButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Apply')),
        ],
      ),
    );
    if (ok != true) return;
    setState(() => _applying = persona['id'] as String);
    try {
      final split = splitPersonaPatch(
          (persona['patch'] as Map).cast<String, dynamic>(), audioFields);
      if (split.camera.isNotEmpty) await widget.onPatch(split.camera);
      if (split.audio.isNotEmpty) await widget.onPatchAudio(split.audio);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    } finally {
      if (mounted) setState(() => _applying = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!widget.isAdmin) return const SizedBox.shrink();
    final data = ref.watch(personasProvider).value;
    if (data == null) return const SizedBox.shrink();
    final personas = (data['personas'] as List? ?? const [])
        .whereType<Map>()
        .map((p) => p.cast<String, dynamic>())
        .toList();
    final audioFields =
        (data['audio_fields'] as List? ?? const []).map((f) => '$f').toList();
    if (personas.isEmpty) return const SizedBox.shrink();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        widget.sectionLabel('QUICK SETUP'),
        Card(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Set this camera up for a common job in one tap.',
                  style: TextStyle(fontSize: 12, color: NurbyColors.mutedForeground),
                ),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  children: [
                    for (final p in personas)
                      ActionChip(
                        avatar: _applying == p['id']
                            ? const SizedBox(
                                width: 12,
                                height: 12,
                                child: CircularProgressIndicator(strokeWidth: 2))
                            : null,
                        label: Text('${p['label']}',
                            style: const TextStyle(fontSize: 12)),
                        tooltip: '${p['hint']}',
                        onPressed: _applying != null
                            ? null
                            : () => _apply(p, audioFields),
                      ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}
