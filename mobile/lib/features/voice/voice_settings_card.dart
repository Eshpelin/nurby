import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../cameras/config_tiles.dart';

/// Household-wide voice settings, including the disclosure allowlist.
///
/// The voice feature shipped with a live conversation card on mobile and
/// nothing else, so a household could watch a camera talk to a visitor
/// from their phone but could not decide what it was allowed to say. That
/// is the wrong half to leave on a laptop: the live card is the rare
/// surface, these settings are the ones that have to be trusted.
///
/// The copy here deliberately matches the web card word for word. Two
/// differently worded explanations of what a camera may disclose is how a
/// household ends up believing the more permissive one.

/// The write payload for a disclosure toggle.
///
/// Pulled out as a function because the read and write names differ: the
/// API returns the allowlist as `voice_may_confirm` and accepts it as
/// `may_confirm`. Sending the read name stores a key the API ignores,
/// which shows on screen as a permission that is on while the disclosure
/// filter treats it as off. That is the worst failure this card could
/// have, so it is one testable place rather than inline in a callback.
Map<String, dynamic> disclosurePatch(
  List<String> current,
  String key, {
  required bool allow,
}) {
  final next = current.where((k) => k != key).toList();
  if (allow) next.add(key);
  return {'may_confirm': next};
}

final voiceSettingsProvider = FutureProvider<Map<String, dynamic>>(
    (ref) => ref.watch(voiceRepoProvider).settings());

class VoiceSettingsCard extends ConsumerWidget {
  const VoiceSettingsCard({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(voiceSettingsProvider);

    return async.when(
      loading: () => const Card(
        child: ListTile(
          leading: Icon(Icons.record_voice_over_outlined),
          title: Text('Camera voice'),
          subtitle: Text('Loading'),
        ),
      ),
      error: (e, _) => Card(
        child: ListTile(
          leading: const Icon(Icons.record_voice_over_outlined),
          title: const Text('Camera voice'),
          subtitle: Text(apiErrorMessage(e), style: _sub),
          trailing: IconButton(
            icon: const Icon(Icons.refresh, size: 18),
            onPressed: () => ref.invalidate(voiceSettingsProvider),
          ),
        ),
      ),
      data: (s) => _Card(settings: s),
    );
  }
}

class _Card extends ConsumerStatefulWidget {
  const _Card({required this.settings});
  final Map<String, dynamic> settings;

  @override
  ConsumerState<_Card> createState() => _CardState();
}

class _CardState extends ConsumerState<_Card> {
  bool _saving = false;

  Map<String, dynamic> get s => widget.settings;

  List<String> _list(String key) =>
      (s[key] as List? ?? const []).map((e) => e.toString()).toList();

  Future<void> _save(Map<String, dynamic> patch) async {
    setState(() => _saving = true);
    try {
      await ref.read(voiceRepoProvider).updateSettings(patch);
      ref.invalidate(voiceSettingsProvider);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final enabled = s['voice_enabled'] as bool? ?? false;
    final allowed = _list('voice_may_confirm');
    final never = _list('voice_never_say');
    final keys = (s['disclosure_keys'] as List? ?? [])
        .whereType<Map>()
        .map((k) => k.cast<String, dynamic>())
        .toList();
    final forbidden = _list('always_forbidden');

    return Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ListTile(
            leading: const Icon(Icons.record_voice_over_outlined,
                color: NurbyColors.accent),
            title: const Text('Camera voice'),
            subtitle: Text(
              enabled
                  ? '${allowed.length} of ${keys.length} disclosures allowed'
                  : 'Off. Cameras will not speak.',
              style: _sub,
            ),
            trailing: _saving
                ? const SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(strokeWidth: 2))
                : null,
          ),
          const Divider(height: 1),
          ConfigSwitch(
            title: 'Let cameras speak',
            value: enabled,
            onChanged: (v) => _save({'voice_enabled': v}),
          ),
          ConfigSwitch(
            title: 'Hold a conversation',
            subtitle: 'Answers a visitor rather than playing one line at them.',
            value: s['voice_conversation_enabled'] as bool? ?? false,
            enabled: enabled,
            onChanged: (v) => _save({'voice_conversation_enabled': v}),
          ),

          AdvancedFold(children: [
          ConfigNumber(
            title: 'Maximum volume',
            value: s['voice_max_volume'] as int? ?? 70,
            min: 1,
            max: 100,
            enabled: enabled,
            onChanged: (v) => _save({'voice_max_volume': v}),
          ),

          ConfigNumber(
            title: 'End a conversation after',
            value: s['voice_session_max_turns'] as int? ?? 6,
            min: 1,
            max: 50,
            suffix: 'turns',
            enabled: enabled,
            onChanged: (v) => _save({'voice_session_max_turns': v}),
          ),

          ConfigNumber(
            title: 'Or after',
            value: s['voice_session_max_seconds'] as int? ?? 120,
            min: 10,
            max: 900,
            suffix: 'seconds',
            enabled: enabled,
            onChanged: (v) => _save({'voice_session_max_seconds': v}),
          ),
          ]),
          _QuietHours(
            start: s['voice_quiet_hours_start'] as String?,
            end: s['voice_quiet_hours_end'] as String?,
            enabled: enabled,
            onChanged: (start, end) => _save({
              'voice_quiet_hours_start': start,
              'voice_quiet_hours_end': end,
            }),
          ),

          // The gap this card exists to close: may_confirm and never_say
          // are honoured all the way through the disclosure filter, but
          // until now no mobile surface wrote them.
          _heading('What a camera may confirm'),
          _body('Everything here is off unless you turn it on. Each one '
              'tells a stranger something about your household.'),
          for (final entry in keys)
            CheckboxListTile(
              value: allowed.contains(entry['key']),
              activeColor: NurbyColors.warning,
              controlAffinity: ListTileControlAffinity.leading,
              dense: true,
              title: Text('${entry['label']}',
                  style: const TextStyle(fontSize: 13)),
              subtitle: Text('${entry['description']}', style: _sub),
              onChanged: enabled
                  ? (on) => _save(disclosurePatch(
                      allowed,
                      entry['key'] as String,
                      allow: on == true,
                    ))
                  : null,
            ),

          // Said plainly so nobody hunts for a switch that does not and
          // should not exist. These three are structural: no setting
          // unlocks them.
          if (forbidden.isNotEmpty)
            Container(
              margin: const EdgeInsets.fromLTRB(16, 8, 16, 4),
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                border: Border.all(color: NurbyColors.border),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('Never allowed, whatever you choose',
                      style: TextStyle(
                          fontSize: 12, fontWeight: FontWeight.w600)),
                  const SizedBox(height: 4),
                  for (final item in forbidden)
                    Padding(
                      padding: const EdgeInsets.only(top: 2),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text('• ', style: _sub),
                          Expanded(child: Text(item, style: _sub)),
                        ],
                      ),
                    ),
                ],
              ),
            ),

          _heading('Never say'),
          _body('Anything you would rather a camera never said out loud.'),
          _PhraseInput(
            phrases: never,
            enabled: enabled,
            onChanged: (next) => _save({'never_say': next}),
          ),
          const SizedBox(height: 8),
        ],
      ),
    );
  }

  Widget _heading(String text) => Padding(
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 2),
        child:
            Text(text, style: const TextStyle(fontWeight: FontWeight.w600)),
      );

  Widget _body(String text) => Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 6),
        child: Text(text, style: _sub),
      );
}

/// Quiet hours are a pair or nothing. Writing one half would leave a
/// window with no other edge, which the speaker policy reads as no quiet
/// hours at all, so both are cleared and set together.
class _QuietHours extends StatelessWidget {
  const _QuietHours({
    required this.start,
    required this.end,
    required this.enabled,
    required this.onChanged,
  });

  final String? start;
  final String? end;
  final bool enabled;
  final void Function(String?, String?) onChanged;

  bool get _set => (start?.isNotEmpty ?? false) && (end?.isNotEmpty ?? false);

  @override
  Widget build(BuildContext context) => ListTile(
        title: const Text('Quiet hours'),
        subtitle: Text(_set ? '$start to $end' : 'None', style: _sub),
        enabled: enabled,
        trailing: _set && enabled
            ? IconButton(
                icon: const Icon(Icons.clear, size: 18),
                tooltip: 'Clear quiet hours',
                onPressed: () => onChanged(null, null),
              )
            : (enabled
                ? const Icon(Icons.chevron_right,
                    size: 20, color: NurbyColors.mutedForeground)
                : null),
        onTap: enabled ? () => _pick(context) : null,
      );

  Future<void> _pick(BuildContext context) async {
    final from = await showTimePicker(
      context: context,
      initialTime: _parse(start) ?? const TimeOfDay(hour: 22, minute: 0),
      helpText: 'Quiet hours start',
    );
    if (from == null || !context.mounted) return;
    final to = await showTimePicker(
      context: context,
      initialTime: _parse(end) ?? const TimeOfDay(hour: 7, minute: 0),
      helpText: 'Quiet hours end',
    );
    if (to == null) return;
    onChanged(_fmt(from), _fmt(to));
  }

  static TimeOfDay? _parse(String? hhmm) {
    final parts = (hhmm ?? '').split(':');
    if (parts.length != 2) return null;
    final h = int.tryParse(parts[0]);
    final m = int.tryParse(parts[1]);
    if (h == null || m == null) return null;
    return TimeOfDay(hour: h, minute: m);
  }

  static String _fmt(TimeOfDay t) =>
      '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
}

class _PhraseInput extends StatefulWidget {
  const _PhraseInput({
    required this.phrases,
    required this.enabled,
    required this.onChanged,
  });

  final List<String> phrases;
  final bool enabled;
  final ValueChanged<List<String>> onChanged;

  @override
  State<_PhraseInput> createState() => _PhraseInputState();
}

class _PhraseInputState extends State<_PhraseInput> {
  final _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _add() {
    final phrase = _controller.text.trim();
    // A duplicate is not an error worth a message, but it should not be
    // stored twice either.
    if (phrase.isEmpty || widget.phrases.contains(phrase)) return;
    widget.onChanged([...widget.phrases, phrase]);
    _controller.clear();
  }

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _controller,
                    enabled: widget.enabled,
                    textInputAction: TextInputAction.done,
                    onSubmitted: (_) => _add(),
                    decoration: const InputDecoration(
                      hintText: 'the dog',
                      isDense: true,
                      border: OutlineInputBorder(),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                OutlinedButton(
                  onPressed: widget.enabled ? _add : null,
                  child: const Text('Add'),
                ),
              ],
            ),
            const SizedBox(height: 8),
            if (widget.phrases.isEmpty)
              const Text('Nothing yet.', style: _sub)
            else
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: [
                  for (final p in widget.phrases)
                    Chip(
                      label: Text(p, style: const TextStyle(fontSize: 12)),
                      onDeleted: widget.enabled
                          ? () => widget.onChanged(
                              widget.phrases.where((x) => x != p).toList())
                          : null,
                    ),
                ],
              ),
          ],
        ),
      );
}

const _sub = TextStyle(color: NurbyColors.mutedForeground, fontSize: 12);
