import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';

/// Guardian detail cards (issue #165).
///
/// Every read here is capability-gated server-side. A 403 means the
/// link's tier does not include this, which is a normal state and not a
/// failure: the household chose that tier deliberately. So a refused
/// card says which tier would show it, rather than surfacing an error a
/// guardian can do nothing about.

final wellbeingProvider =
    FutureProvider.family<Map<String, dynamic>, String>((ref, id) =>
        ref.watch(guardianRepoProvider).wellbeing(id));

final trendsProvider = FutureProvider.family<Map<String, dynamic>, String>(
    (ref, id) => ref.watch(guardianRepoProvider).trends(id));

final guardianEventsProvider =
    FutureProvider.family<Map<String, dynamic>, String>(
        (ref, id) => ref.watch(guardianRepoProvider).events(id));

final guardianActionsProvider =
    FutureProvider.family<Map<String, dynamic>, String>(
        (ref, id) => ref.watch(guardianRepoProvider).actions(id));

bool isForbidden(Object e) =>
    e is DioException && e.response?.statusCode == 403;

/// The three absolute rules of this screen's copy, in one place:
/// wellbeing signals are best-effort, a delayed view says so, and a
/// refused capability names itself rather than erroring.
const kBestEffortNote =
    'These are best-effort signals from what the cameras saw. They are '
    'not a medical record.';

class GuardianSection extends StatelessWidget {
  const GuardianSection({
    super.key,
    required this.title,
    required this.child,
    this.delayed = false,
  });

  final String title;
  final Widget child;

  /// Free-tier links see a time-shifted view. Saying so is the
  /// difference between "nothing happened" and "nothing has reached you
  /// yet", which are very different things to read about a parent.
  final bool delayed;

  @override
  Widget build(BuildContext context) => Card(
        margin: const EdgeInsets.fromLTRB(12, 6, 12, 0),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(title,
                        style: const TextStyle(fontWeight: FontWeight.w600)),
                  ),
                  if (delayed)
                    const Text('delayed view', style: _sub),
                ],
              ),
              const SizedBox(height: 8),
              child,
            ],
          ),
        ),
      );
}

/// What to show when the server refuses a capability.
class TierLocked extends StatelessWidget {
  const TierLocked({super.key, required this.what});

  final String what;

  @override
  Widget build(BuildContext context) => Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.lock_outline,
              size: 14, color: NurbyColors.mutedForeground),
          const SizedBox(width: 6),
          Expanded(
            child: Text('$what is not part of this link\'s access level.',
                style: _sub),
          ),
        ],
      );
}

class WellbeingCard extends ConsumerWidget {
  const WellbeingCard({super.key, required this.linkId});

  final String linkId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(wellbeingProvider(linkId));

    return async.when(
      loading: () => const GuardianSection(
          title: 'Wellbeing', child: LinearProgressIndicator()),
      error: (e, _) => GuardianSection(
        title: 'Wellbeing',
        child: isForbidden(e)
            ? const TierLocked(what: 'Wellbeing')
            : Text(apiErrorMessage(e), style: _sub),
      ),
      data: (w) {
        final counts = (w['counts'] as Map? ?? {}).map(
            (k, v) => MapEntry('$k', (v as num?)?.toInt() ?? 0));
        final lastFall = w['last_fall_at'] as String?;
        final last = (w['last_action'] as Map?)?.cast<String, dynamic>();

        return GuardianSection(
          title: 'Wellbeing',
          delayed: w['delayed'] == true,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(
                    w['ate_today'] == true
                        ? Icons.restaurant
                        : Icons.restaurant_outlined,
                    size: 16,
                    color: w['ate_today'] == true
                        ? NurbyColors.accent
                        : NurbyColors.mutedForeground,
                  ),
                  const SizedBox(width: 8),
                  Text(
                    w['ate_today'] == true
                        ? 'Seen eating today'
                        : 'Not seen eating today',
                    style: const TextStyle(fontSize: 13),
                  ),
                ],
              ),
              // A fall is the one signal here worth showing loudly, and
              // the one where a stale reading would be worst, so it
              // always carries its timestamp.
              if (lastFall != null) ...[
                const SizedBox(height: 6),
                Row(
                  children: [
                    const Icon(Icons.warning_amber_rounded,
                        size: 16, color: NurbyColors.warning),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        'Possible fall detected ${_ago(lastFall)}',
                        style: const TextStyle(
                            fontSize: 13, color: NurbyColors.warning),
                      ),
                    ),
                  ],
                ),
              ],
              if (last != null) ...[
                const SizedBox(height: 6),
                Text('Last seen ${last['action']} ${_ago('${last['at']}')}',
                    style: _sub),
              ],
              if (counts.isNotEmpty) ...[
                const SizedBox(height: 10),
                Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  children: [
                    for (final e in counts.entries)
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 8, vertical: 3),
                        decoration: BoxDecoration(
                          color: NurbyColors.accent.withValues(alpha: 0.12),
                          borderRadius: BorderRadius.circular(4),
                        ),
                        child: Text('${e.key} ${e.value}',
                            style: const TextStyle(fontSize: 11)),
                      ),
                  ],
                ),
              ],
              const SizedBox(height: 10),
              const Text(kBestEffortNote, style: _sub),
            ],
          ),
        );
      },
    );
  }
}

class TrendsCard extends ConsumerWidget {
  const TrendsCard({super.key, required this.linkId});

  final String linkId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(trendsProvider(linkId));

    return async.when(
      loading: () => const GuardianSection(
          title: 'Recent days', child: LinearProgressIndicator()),
      error: (e, _) => GuardianSection(
        title: 'Recent days',
        child: isForbidden(e)
            ? const TierLocked(what: 'Trends')
            : Text(apiErrorMessage(e), style: _sub),
      ),
      data: (t) {
        final days = (t['days'] as List? ?? [])
            .whereType<Map>()
            .map((d) => d.cast<String, dynamic>())
            .toList();
        final peak = days.fold<int>(
            0, (a, d) => ((d['sightings'] as num?)?.toInt() ?? 0) > a
                ? (d['sightings'] as num).toInt()
                : a);

        return GuardianSection(
          title: 'Recent days',
          delayed: t['delayed'] == true,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Seen on ${t['days_seen'] ?? 0} of ${t['window_days'] ?? 0} days',
                style: const TextStyle(fontSize: 13),
              ),
              const SizedBox(height: 10),
              SizedBox(
                // Bar (max 32) + gap (3) + the day letter. Sized to fit
                // all three rather than clipping the label.
                height: 52,
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    for (final d in days)
                      Expanded(
                        child: Padding(
                          padding: const EdgeInsets.symmetric(horizontal: 2),
                          child: Column(
                            mainAxisAlignment: MainAxisAlignment.end,
                            children: [
                              Container(
                                // A day with no sightings keeps a
                                // hairline so it reads as a quiet day
                                // rather than a missing one.
                                height: peak == 0
                                    ? 2
                                    : 2 +
                                        30 *
                                            ((d['sightings'] as num?)
                                                    ?.toDouble() ??
                                                0) /
                                            peak,
                                decoration: BoxDecoration(
                                  color: ((d['sightings'] as num?) ?? 0) == 0
                                      ? NurbyColors.border
                                      : NurbyColors.accent,
                                  borderRadius: BorderRadius.circular(2),
                                ),
                              ),
                              const SizedBox(height: 3),
                              Text(_dayLabel('${d['date']}'),
                                  style: const TextStyle(
                                      fontSize: 9,
                                      color: NurbyColors.mutedForeground)),
                            ],
                          ),
                        ),
                      ),
                  ],
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

class GuardianEventsCard extends ConsumerWidget {
  const GuardianEventsCard({super.key, required this.linkId});

  final String linkId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(guardianEventsProvider(linkId));

    return async.when(
      loading: () => const GuardianSection(
          title: 'Alerts', child: LinearProgressIndicator()),
      error: (e, _) => GuardianSection(
        title: 'Alerts',
        child: isForbidden(e)
            ? const TierLocked(what: 'Alerts')
            : Text(apiErrorMessage(e), style: _sub),
      ),
      data: (r) {
        final items = (r['items'] as List? ?? [])
            .whereType<Map>()
            .map((i) => i.cast<String, dynamic>())
            .toList();
        return GuardianSection(
          title: 'Alerts',
          child: items.isEmpty
              ? const Text('Nothing raised recently.', style: _sub)
              : Column(
                  children: [
                    for (final e in items.take(12))
                      Padding(
                        padding: const EdgeInsets.symmetric(vertical: 3),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Icon(_severityIcon('${e['severity']}'),
                                size: 14, color: _severityColor('${e['severity']}')),
                            const SizedBox(width: 8),
                            Expanded(
                              child: Text('${e['message'] ?? e['kind']}',
                                  style: const TextStyle(fontSize: 12)),
                            ),
                            Text(_ago('${e['at']}'), style: _sub),
                          ],
                        ),
                      ),
                  ],
                ),
        );
      },
    );
  }
}

final liveProvider = FutureProvider.family<Map<String, dynamic>, String>(
    (ref, id) => ref.watch(guardianRepoProvider).live(id));

/// What can be looked at right now.
///
/// Presence, a recent still, and a recent clip are three separate
/// entitlements, and a link can have any combination. Each is shown only
/// when the server says it is there, rather than rendering a broken
/// image or a dead play button.
class LiveCard extends ConsumerWidget {
  const LiveCard({super.key, required this.linkId});

  final String linkId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(liveProvider(linkId));

    return async.when(
      loading: () => const GuardianSection(
          title: 'Right now', child: LinearProgressIndicator()),
      error: (e, _) => GuardianSection(
        title: 'Right now',
        child: isForbidden(e)
            ? const TierLocked(what: 'Live view')
            : Text(apiErrorMessage(e), style: _sub),
      ),
      data: (l) {
        final hasImage = l['image_available'] == true;
        final hasClip = l['clip_available'] == true;
        final repo = ref.read(guardianRepoProvider);

        if (!hasImage && !hasClip) {
          return const GuardianSection(
            title: 'Right now',
            child: Text('Nothing recent to show.', style: _sub),
          );
        }

        return GuardianSection(
          title: 'Right now',
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (hasImage)
                ClipRRect(
                  borderRadius: BorderRadius.circular(8),
                  child: Image.network(
                    repo.imageUrl(linkId),
                    fit: BoxFit.cover,
                    // The still can expire between the availability check
                    // and the fetch. A broken-image icon would read as a
                    // fault in the camera rather than in the timing.
                    errorBuilder: (_, __, ___) => const Padding(
                      padding: EdgeInsets.symmetric(vertical: 12),
                      child: Text('That still is no longer available.',
                          style: _sub),
                    ),
                  ),
                ),
              if (hasClip) ...[
                const SizedBox(height: 8),
                Row(
                  children: [
                    const Icon(Icons.videocam_outlined,
                        size: 16, color: NurbyColors.mutedForeground),
                    const SizedBox(width: 8),
                    const Expanded(
                        child: Text('A recent clip is available.',
                            style: _sub)),
                  ],
                ),
              ],
            ],
          ),
        );
      },
    );
  }
}

/// What the dependant was seen doing, most recent first.
class ActionsCard extends ConsumerWidget {
  const ActionsCard({super.key, required this.linkId});

  final String linkId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(guardianActionsProvider(linkId));

    return async.when(
      loading: () => const GuardianSection(
          title: 'Seen doing', child: LinearProgressIndicator()),
      error: (e, _) => GuardianSection(
        title: 'Seen doing',
        child: isForbidden(e)
            ? const TierLocked(what: 'Activity')
            : Text(apiErrorMessage(e), style: _sub),
      ),
      data: (r) {
        final items = (r['items'] as List? ?? [])
            .whereType<Map>()
            .map((i) => i.cast<String, dynamic>())
            .toList();
        return GuardianSection(
          title: 'Seen doing',
          delayed: r['delayed'] == true,
          child: items.isEmpty
              ? const Text('Nothing recorded recently.', style: _sub)
              : Column(
                  children: [
                    for (final a in items.take(15))
                      Padding(
                        padding: const EdgeInsets.symmetric(vertical: 3),
                        child: Row(
                          children: [
                            Expanded(
                              child: Text('${a['action'] ?? 'Activity'}',
                                  style: const TextStyle(fontSize: 12)),
                            ),
                            if (a['at'] != null)
                              Text(_ago('${a['at']}'), style: _sub),
                          ],
                        ),
                      ),
                  ],
                ),
        );
      },
    );
  }
}

/// Ask a question about this one dependant.
///
/// Scoped to the link server-side, so it can never reach anything the
/// tier does not already allow. Worth saying on screen: a guardian
/// should not have to wonder whether asking widens their access.
class GuardianSearchCard extends ConsumerStatefulWidget {
  const GuardianSearchCard({super.key, required this.linkId, required this.name});

  final String linkId;
  final String name;

  @override
  ConsumerState<GuardianSearchCard> createState() =>
      _GuardianSearchCardState();
}

class _GuardianSearchCardState extends ConsumerState<GuardianSearchCard> {
  final _controller = TextEditingController();
  bool _busy = false;
  String? _answer;
  String? _error;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _ask() async {
    final q = _controller.text.trim();
    if (q.isEmpty) return;
    setState(() {
      _busy = true;
      _error = null;
      _answer = null;
    });
    try {
      final r = await ref.read(guardianRepoProvider).search(widget.linkId, q);
      if (!mounted) return;
      setState(() => _answer =
          (r['answer'] ?? r['text'] ?? r['summary'])?.toString().trim());
    } catch (e) {
      if (mounted) {
        setState(() => _error = isForbidden(e)
            ? 'Asking questions is not part of this link\'s access level.'
            : apiErrorMessage(e));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => GuardianSection(
        title: 'Ask about ${widget.name}',
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _controller,
                    textInputAction: TextInputAction.search,
                    onSubmitted: (_) => _ask(),
                    decoration: const InputDecoration(
                      hintText: 'Did she go out this morning?',
                      isDense: true,
                      border: OutlineInputBorder(),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                FilledButton(
                  onPressed: _busy ? null : _ask,
                  child: const Text('Ask'),
                ),
              ],
            ),
            if (_answer != null) ...[
              const SizedBox(height: 10),
              Text(_answer!, style: const TextStyle(fontSize: 13)),
            ],
            if (_error != null) ...[
              const SizedBox(height: 10),
              Text(_error!, style: _sub),
            ],
            const SizedBox(height: 8),
            const Text(
              'Answers are limited to what this link already lets you see.',
              style: _sub,
            ),
          ],
        ),
      );
}

class AlertPrefsCard extends ConsumerStatefulWidget {
  const AlertPrefsCard({
    super.key,
    required this.linkId,
    required this.alertPrefs,
    required this.notifyChannels,
  });

  final String linkId;
  final Map<String, dynamic> alertPrefs;
  final Map<String, dynamic> notifyChannels;

  @override
  ConsumerState<AlertPrefsCard> createState() => _AlertPrefsCardState();
}

class _AlertPrefsCardState extends ConsumerState<AlertPrefsCard> {
  bool _busy = false;

  /// Server-side defaults, mirrored so an unset key reads the way the
  /// backend will actually treat it rather than as "off".
  static const _defaults = {
    'arrived': true,
    'departed': true,
    'picked_up': true,
    'entered_zone': false,
    'left_zone': false,
    'not_seen': false,
    'fell': true,
    'attended_meal': true,
  };

  static const _labels = {
    'arrived': 'Arrived home',
    'departed': 'Left home',
    'picked_up': 'Picked up by someone',
    'entered_zone': 'Entered an area',
    'left_zone': 'Left an area',
    'not_seen': 'Not seen for a while',
    'fell': 'Possible fall',
    'attended_meal': 'Ate a meal',
  };

  static const _channelLabels = {
    'telegram': 'Telegram',
    'email': 'Email',
    'in_app': 'In the app',
  };

  bool _pref(String key) =>
      widget.alertPrefs[key] as bool? ?? _defaults[key] ?? false;

  bool _channel(String key) => widget.notifyChannels[key] as bool? ?? true;

  Future<void> _save(Future<void> Function() call) async {
    setState(() => _busy = true);
    try {
      await call();
      ref.invalidate(guardianLinksProvider);
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
    final repo = ref.read(guardianRepoProvider);

    return GuardianSection(
      title: 'What to tell me about',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final key in _defaults.keys)
            SwitchListTile(
              dense: true,
              contentPadding: EdgeInsets.zero,
              title: Text(_labels[key] ?? key,
                  style: const TextStyle(fontSize: 13)),
              value: _pref(key),
              activeColor: NurbyColors.accent,
              onChanged: _busy
                  ? null
                  : (on) => _save(() async {
                        final next = {
                          for (final k in _defaults.keys) k: _pref(k),
                        }..[key] = on;
                        await repo.updateAlerts(widget.linkId, next);
                      }),
            ),
          const Divider(),
          const Text('How to reach me',
              style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
          const SizedBox(height: 4),
          Wrap(
            spacing: 6,
            children: [
              for (final key in _channelLabels.keys)
                FilterChip(
                  label: Text(_channelLabels[key]!,
                      style: const TextStyle(fontSize: 12)),
                  selected: _channel(key),
                  onSelected: _busy
                      ? null
                      : (on) => _save(() async {
                            final next = {
                              for (final k in _channelLabels.keys)
                                k: _channel(k),
                            }..[key] = on;
                            await repo.updateChannels(widget.linkId, next);
                          }),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

/// Shared so the alert editor can refresh the list it came from.
final guardianLinksProvider = FutureProvider<List<Map<String, dynamic>>>(
    (ref) => ref.watch(guardianRepoProvider).links());

// ---- formatting ----

String _dayLabel(String iso) {
  final d = DateTime.tryParse(iso);
  return d == null ? '' : DateFormat('E').format(d).substring(0, 1);
}

String _ago(String iso) {
  final d = DateTime.tryParse(iso);
  if (d == null) return '';
  final diff = DateTime.now().difference(d.toLocal());
  if (diff.inMinutes < 1) return 'just now';
  if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
  if (diff.inHours < 24) return '${diff.inHours}h ago';
  return '${diff.inDays}d ago';
}

IconData _severityIcon(String s) => switch (s) {
      'critical' || 'high' => Icons.error_outline,
      'warning' => Icons.warning_amber_rounded,
      _ => Icons.info_outline,
    };

Color _severityColor(String s) => switch (s) {
      'critical' || 'high' => NurbyColors.danger,
      'warning' => NurbyColors.warning,
      _ => NurbyColors.mutedForeground,
    };

const _sub = TextStyle(color: NurbyColors.mutedForeground, fontSize: 12);
