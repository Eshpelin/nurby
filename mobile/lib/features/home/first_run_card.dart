import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../models/models.dart';
import '../cameras/add_camera_sheet.dart';

/// First run: from installed to a first useful alert.
///
/// Mobile had no onboarding at all. The checklist is four steps because
/// four is what it takes to get value: see something, tune it, be told
/// about something, ask a question. It disappears for good once the
/// household has a camera and a rule, so it is not furniture.
final _rulesCountProvider = FutureProvider<int>((ref) async =>
    (await ref.watch(ruleRepoProvider).list()).length);

final starterRulesProvider = FutureProvider<List<Map<String, dynamic>>>(
    (ref) => ref.watch(ruleRepoProvider).starters());

/// Whether the card should show at all. Pure, so the rule is one place.
bool showFirstRun({required int cameras, required int rules, required bool dismissed}) =>
    !dismissed && (cameras == 0 || rules == 0);

class FirstRunCard extends ConsumerStatefulWidget {
  const FirstRunCard({super.key});

  @override
  ConsumerState<FirstRunCard> createState() => _FirstRunCardState();
}

class _FirstRunCardState extends ConsumerState<FirstRunCard> {
  bool _dismissed = false;
  bool _busy = false;

  Future<void> _createStarter(String key, List<Camera> cameras) async {
    // One camera: use it. Several: ask which, because "every camera"
    // for a package rule means a notification from the back garden too.
    String? cameraId;
    if (cameras.length == 1) {
      cameraId = cameras.first.id;
    } else if (cameras.length > 1) {
      cameraId = await showModalBottomSheet<String>(
        context: context,
        backgroundColor: NurbyColors.cardElevated,
        builder: (ctx) => SafeArea(
          child: ListView(
            shrinkWrap: true,
            children: [
              const Padding(
                padding: EdgeInsets.fromLTRB(16, 16, 16, 8),
                child: Text('Which camera?',
                    style: TextStyle(fontWeight: FontWeight.w600)),
              ),
              for (final c in cameras)
                ListTile(title: Text(c.name), onTap: () => Navigator.pop(ctx, c.id)),
              ListTile(
                title: const Text('Every camera'),
                subtitle: const Text('You can narrow it later',
                    style: TextStyle(fontSize: 12, color: NurbyColors.mutedForeground)),
                onTap: () => Navigator.pop(ctx, ''),
              ),
            ],
          ),
        ),
      );
      if (cameraId == null) return; // dismissed
      if (cameraId.isEmpty) cameraId = null;
    }

    setState(() => _busy = true);
    try {
      await ref.read(ruleRepoProvider).createFromStarter(key, cameraId: cameraId);
      ref.invalidate(_rulesCountProvider);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text("Done. You'll be told when it happens.")));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final cameras = ref.watch(camerasProvider).value ?? const <Camera>[];
    final rules = ref.watch(_rulesCountProvider).value;
    if (rules == null) return const SizedBox.shrink();
    if (!showFirstRun(cameras: cameras.length, rules: rules, dismissed: _dismissed)) {
      return const SizedBox.shrink();
    }
    final starters = ref.watch(starterRulesProvider).value ?? const [];

    return Card(
      margin: const EdgeInsets.fromLTRB(12, 12, 12, 4),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 12, 8, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Expanded(
                  child: Text('Getting started',
                      style: TextStyle(fontWeight: FontWeight.w600)),
                ),
                IconButton(
                  icon: const Icon(Icons.close, size: 18),
                  tooltip: 'Hide',
                  onPressed: () => setState(() => _dismissed = true),
                ),
              ],
            ),
            _Step(
              done: cameras.isNotEmpty,
              title: 'Add a camera',
              hint: 'Scan the network or type a stream URL.',
              action: 'Add',
              onTap: () => showAddCameraSheet(context, ref),
            ),
            _Step(
              done: cameras.isNotEmpty,
              title: 'Tell it what the camera is for',
              hint: 'Front door, driveway, baby cam. One tap sets it up.',
              action: 'Set up',
              enabled: cameras.isNotEmpty,
              onTap: () => context.go('/cameras/${cameras.first.id}'),
            ),
            _Step(
              done: rules > 0,
              title: 'Pick one thing to be told about',
              hint: rules > 0 ? null : 'This is the step that makes Nurby useful.',
              enabled: cameras.isNotEmpty,
            ),
            if (rules == 0 && cameras.isNotEmpty && starters.isNotEmpty)
              Padding(
                padding: const EdgeInsets.fromLTRB(30, 0, 8, 8),
                child: Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  children: [
                    for (final s in starters)
                      ActionChip(
                        label: Text('${s['title']}',
                            style: const TextStyle(fontSize: 12)),
                        onPressed: _busy
                            ? null
                            : () => _createStarter('${s['key']}', cameras),
                      ),
                  ],
                ),
              ),
            _Step(
              done: false,
              title: 'Ask Nurby something',
              hint: 'Try "what happened today?"',
              action: 'Ask',
              enabled: cameras.isNotEmpty,
              onTap: () => context.go('/ask'),
            ),
          ],
        ),
      ),
    );
  }
}

class _Step extends StatelessWidget {
  const _Step({
    required this.done,
    required this.title,
    this.hint,
    this.action,
    this.onTap,
    this.enabled = true,
  });

  final bool done;
  final String title;
  final String? hint;
  final String? action;
  final VoidCallback? onTap;
  final bool enabled;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(
              done ? Icons.check_circle : Icons.radio_button_unchecked,
              size: 18,
              color: done ? NurbyColors.accent : NurbyColors.mutedForeground,
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Padding(
                    padding: const EdgeInsets.only(top: 1),
                    child: Text(title,
                        style: TextStyle(
                          fontSize: 13,
                          color: enabled ? null : NurbyColors.mutedForeground,
                          decoration: done ? TextDecoration.lineThrough : null,
                          decorationColor: NurbyColors.mutedForeground,
                        )),
                  ),
                  if (hint != null && !done)
                    Text(hint!,
                        style: const TextStyle(
                            fontSize: 11, color: NurbyColors.mutedForeground)),
                ],
              ),
            ),
            if (action != null && !done)
              TextButton(
                onPressed: enabled ? onTap : null,
                child: Text(action!),
              ),
          ],
        ),
      );
}
