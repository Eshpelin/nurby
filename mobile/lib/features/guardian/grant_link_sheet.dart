import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../models/models.dart';
import 'guardian_admin_screen.dart';

/// Grant someone outside the household a view of one person (#165).
///
/// Four steps, one screen each, because this is the one place the app
/// hands access to an outsider and every choice here narrows or widens
/// what they see: who, of whom, how much, for how long. A single form
/// with fourteen fields buries the one that matters on each step.
class GrantLinkSheet extends ConsumerStatefulWidget {
  const GrantLinkSheet({super.key});

  @override
  ConsumerState<GrantLinkSheet> createState() => _GrantLinkSheetState();
}

final _peopleProvider = FutureProvider<List<Person>>((ref) async {
  final j = await ref.watch(apiClientProvider).getJson('/api/persons') as List;
  return j.whereType<Map>().map((p) => Person.fromJson(p.cast<String, dynamic>())).toList();
});

class _GrantLinkSheetState extends ConsumerState<GrantLinkSheet> {
  int _step = 0;
  final _email = TextEditingController();
  final _label = TextEditingController();
  Person? _person;
  String _tier = 'summary';
  bool _liveVideo = false;
  bool _audio = false;
  bool _livePresence = false;
  int? _expiryDays;
  bool _busy = false;
  String? _error;
  Map<String, dynamic>? _result;

  @override
  void dispose() {
    _email.dispose();
    _label.dispose();
    super.dispose();
  }

  static const _tiers = [
    ('alerts_only', 'Alerts only', 'Told when something happens. Sees nothing else.'),
    ('summary', 'Summaries', 'Status, recaps and the timeline. No live view.'),
    ('full', 'Full', 'Everything, including live video if switched on below.'),
  ];

  bool get _canNext => switch (_step) {
        0 => _email.text.trim().contains('@'),
        1 => _person != null,
        _ => true,
      };

  Future<void> _grant() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final r = await ref.read(guardianRepoProvider).createLink({
        'guardian_email': _email.text.trim(),
        'person_id': _person!.id,
        if (_label.text.trim().isNotEmpty) 'relationship_label': _label.text.trim(),
        'tier': _tier,
        'live_video': _tier == 'full' && _liveVideo,
        'audio': _tier == 'full' && _audio,
        'live_presence': _livePresence,
        if (_expiryDays != null)
          'expires_at': DateTime.now()
              .toUtc()
              .add(Duration(days: _expiryDays!))
              .toIso8601String(),
      });
      ref.invalidate(grantedLinksProvider);
      if (mounted) setState(() => _result = r);
    } catch (e) {
      if (mounted) setState(() => _error = apiErrorMessage(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_result != null) return _Done(result: _result!);

    return Padding(
      padding: EdgeInsets.only(
        left: 20,
        right: 20,
        top: 20,
        bottom: MediaQuery.of(context).viewInsets.bottom + 24,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Text('Step ${_step + 1} of 4',
                  style: const TextStyle(
                      fontSize: 11, color: NurbyColors.mutedForeground)),
              const Spacer(),
              for (var i = 0; i < 4; i++)
                Container(
                  width: 18,
                  height: 3,
                  margin: const EdgeInsets.only(left: 3),
                  color: i <= _step ? NurbyColors.accent : NurbyColors.border,
                ),
            ],
          ),
          const SizedBox(height: 12),
          switch (_step) {
            0 => _who(),
            1 => _ofWhom(),
            2 => _howMuch(),
            _ => _howLong(),
          },
          if (_error != null) ...[
            const SizedBox(height: 10),
            Text(_error!,
                style: const TextStyle(color: NurbyColors.danger, fontSize: 13)),
          ],
          const SizedBox(height: 16),
          Row(
            children: [
              if (_step > 0)
                TextButton(
                    onPressed: () => setState(() => _step--),
                    child: const Text('Back')),
              const Spacer(),
              TextButton(
                  onPressed: () => Navigator.pop(context),
                  child: const Text('Cancel')),
              const SizedBox(width: 8),
              FilledButton(
                onPressed: !_canNext || _busy
                    ? null
                    : (_step < 3 ? () => setState(() => _step++) : _grant),
                child: Text(_step < 3 ? 'Next' : 'Grant access'),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _who() => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('Who is this for?',
              style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
          const SizedBox(height: 4),
          const Text(
            'They get an email with a link to set their own password. '
            'If they already have a Nurby account, it is used.',
            style: TextStyle(fontSize: 12, color: NurbyColors.mutedForeground),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _email,
            autofocus: true,
            keyboardType: TextInputType.emailAddress,
            autocorrect: false,
            onChanged: (_) => setState(() {}),
            decoration: const InputDecoration(
                labelText: 'Their email', border: OutlineInputBorder()),
          ),
          const SizedBox(height: 10),
          TextField(
            controller: _label,
            decoration: const InputDecoration(
                labelText: 'How you know them (optional)',
                hintText: 'Grandma, carer, school',
                border: OutlineInputBorder()),
          ),
        ],
      );

  Widget _ofWhom() {
    final people = ref.watch(_peopleProvider).value ?? const <Person>[];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('Which person may they watch?',
            style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
        const SizedBox(height: 4),
        const Text(
          'One person per link. Everything they see is filtered to this '
          'person; other people in the frame stay hidden.',
          style: TextStyle(fontSize: 12, color: NurbyColors.mutedForeground),
        ),
        const SizedBox(height: 12),
        if (people.isEmpty)
          const Text('No people yet. Name someone in People first.',
              style: TextStyle(fontSize: 13, color: NurbyColors.mutedForeground))
        else
          Wrap(
            spacing: 6,
            runSpacing: 6,
            children: [
              for (final p in people)
                ChoiceChip(
                  label: Text(p.displayName),
                  selected: _person?.id == p.id,
                  onSelected: (_) => setState(() => _person = p),
                ),
            ],
          ),
      ],
    );
  }

  Widget _howMuch() => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('How much may they see?',
              style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
          const SizedBox(height: 8),
          for (final (key, label, hint) in _tiers)
            RadioListTile<String>(
              value: key,
              groupValue: _tier,
              activeColor: NurbyColors.accent,
              contentPadding: EdgeInsets.zero,
              title: Text(label),
              subtitle: Text(hint,
                  style: const TextStyle(
                      fontSize: 12, color: NurbyColors.mutedForeground)),
              onChanged: (v) => setState(() => _tier = v!),
            ),
          // Live video and audio are the two that let an outsider see
          // and hear a home in real time. They are off by default, only
          // offered on the full tier, and each says what it is.
          if (_tier == 'full') ...[
            const Divider(),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Live video'),
              subtitle: const Text('A live feed of the cameras this person is on.',
                  style: TextStyle(fontSize: 12, color: NurbyColors.mutedForeground)),
              value: _liveVideo,
              activeColor: NurbyColors.accent,
              onChanged: (v) => setState(() => _liveVideo = v),
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Audio'),
              subtitle: const Text('Sound with the video, and clips with sound.',
                  style: TextStyle(fontSize: 12, color: NurbyColors.mutedForeground)),
              value: _audio,
              activeColor: NurbyColors.accent,
              onChanged: (v) => setState(() => _audio = v),
            ),
          ],
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('Live presence'),
            subtitle: const Text('Whether the person is home right now, without delay.',
                style: TextStyle(fontSize: 12, color: NurbyColors.mutedForeground)),
            value: _livePresence,
            activeColor: NurbyColors.accent,
            onChanged: (v) => setState(() => _livePresence = v),
          ),
        ],
      );

  Widget _howLong() => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('For how long?',
              style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
          const SizedBox(height: 4),
          const Text(
            'You can revoke at any time regardless. An end date means you '
            'do not have to remember to.',
            style: TextStyle(fontSize: 12, color: NurbyColors.mutedForeground),
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 6,
            children: [
              for (final (days, label) in [(null, 'No end date'), (7, 'A week'), (30, 'A month'), (90, 'Three months'), (365, 'A year')])
                ChoiceChip(
                  label: Text(label),
                  selected: _expiryDays == days,
                  onSelected: (_) => setState(() => _expiryDays = days),
                ),
            ],
          ),
          const SizedBox(height: 16),
          Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              border: Border.all(color: NurbyColors.border),
              borderRadius: BorderRadius.circular(8),
            ),
            child: Text(
              '${_email.text.trim()} will be able to see '
              '${_person?.displayName ?? 'this person'}: '
              '${_tiers.firstWhere((t) => t.$1 == _tier).$2.toLowerCase()}'
              '${_tier == 'full' && _liveVideo ? ', with live video' : ''}'
              '${_tier == 'full' && _audio ? ' and audio' : ''}'
              '${_expiryDays == null ? ', until revoked.' : ', for ${_expiryDays == 7 ? 'a week' : _expiryDays == 30 ? 'a month' : _expiryDays == 90 ? 'three months' : 'a year'}.'}',
              style: const TextStyle(fontSize: 13),
            ),
          ),
        ],
      );
}

class _Done extends StatelessWidget {
  const _Done({required this.result});

  final Map<String, dynamic> result;

  @override
  Widget build(BuildContext context) {
    final emailed = result['claim_email_sent'] == true;
    final claimUrl = result['claim_url'] as String?;
    final temp = result['temp_password'] as String?;
    final created = result['guardian_created'] == true;

    return Padding(
      padding: const EdgeInsets.all(20),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Icon(Icons.check_circle_outline,
              size: 40, color: NurbyColors.accent),
          const SizedBox(height: 10),
          Text(
            emailed
                ? 'Invite sent to ${result['guardian_email']}.'
                : created
                    ? 'Account created for ${result['guardian_email']}.'
                    : 'Access granted to ${result['guardian_email']}.',
            textAlign: TextAlign.center,
            style: const TextStyle(fontWeight: FontWeight.w600),
          ),
          // No mail server, so the link has to be handed over by hand.
          // Show it once, with a copy button, and say plainly that it is
          // the credential.
          if (!emailed && claimUrl != null) ...[
            const SizedBox(height: 12),
            const Text(
              'Email is not set up, so send them this link yourself. It '
              'lets them set a password, so treat it like one.',
              style: TextStyle(fontSize: 12, color: NurbyColors.mutedForeground),
            ),
            const SizedBox(height: 8),
            _Copyable(claimUrl),
          ] else if (!emailed && temp != null) ...[
            const SizedBox(height: 12),
            const Text(
              'A temporary password was set. Give it to them privately; '
              'it is not shown again.',
              style: TextStyle(fontSize: 12, color: NurbyColors.mutedForeground),
            ),
            const SizedBox(height: 8),
            _Copyable(temp),
          ],
          const SizedBox(height: 16),
          FilledButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('Done')),
        ],
      ),
    );
  }
}

class _Copyable extends StatelessWidget {
  const _Copyable(this.value);
  final String value;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.fromLTRB(12, 8, 4, 8),
        decoration: BoxDecoration(
          color: NurbyColors.background,
          border: Border.all(color: NurbyColors.border),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Row(
          children: [
            Expanded(
              child: Text(value,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontFamily: 'Menlo', fontSize: 11)),
            ),
            IconButton(
              icon: const Icon(Icons.copy, size: 16),
              onPressed: () {
                Clipboard.setData(ClipboardData(text: value));
                ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('Copied.')));
              },
            ),
          ],
        ),
      );
}
