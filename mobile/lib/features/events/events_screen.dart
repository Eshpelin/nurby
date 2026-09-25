import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import 'event_feedback.dart';
import 'event_notes.dart';
import '../../models/models.dart';
import '../shares/share_sheet.dart';

const _pageSize = 50;

typedef EventsQuery = ({bool? acked, String? cameraId});

/// First page of event history per filter.
final eventsProvider = FutureProvider.family<List<Event>, EventsQuery>(
    (ref, q) => ref.watch(eventRepoProvider).history(
          acked: q.acked,
          cameraId: q.cameraId,
          limit: _pageSize,
        ));

/// Observation detail for the "View observation" link-out.
final _observationProvider = FutureProvider.family<Observation, String>(
    (ref, id) => ref.watch(observationRepoProvider).get(id));

/// Alerts tab: rule-fired event history with ack workflow.
class EventsScreen extends ConsumerStatefulWidget {
  const EventsScreen({super.key, this.embedded = false});

  /// Rendered inside the Activity screen: no Scaffold, no app bar.
  final bool embedded;

  @override
  ConsumerState<EventsScreen> createState() => _EventsScreenState();
}

class _EventsScreenState extends ConsumerState<EventsScreen> {
  final _scroll = ScrollController();
  final List<Event> _extra = [];
  bool? _acked = false; // false = unreviewed (default), null = all
  String? _cameraId;
  bool _loadingMore = false;
  bool _hasMore = true;
  final Set<String> _selectedIds = <String>{};
  bool _selectionMode = false;
  bool _allMatching = false;

  EventsQuery get _query => (acked: _acked, cameraId: _cameraId);

  @override
  void initState() {
    super.initState();
    _scroll.addListener(_onScroll);
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  void _onScroll() {
    if (_scroll.position.pixels > _scroll.position.maxScrollExtent - 400) {
      _loadMore();
    }
  }

  void _resetPaging() {
    _extra.clear();
    _hasMore = true;
    _loadingMore = false;
  }

  void _clearSelection() {
    _selectedIds.clear();
    _selectionMode = false;
    _allMatching = false;
  }

  void _toggleSelected(String id) {
    setState(() {
      _selectionMode = true;
      _allMatching = false;
      if (!_selectedIds.add(id)) _selectedIds.remove(id);
      if (_selectedIds.isEmpty) _selectionMode = false;
    });
  }

  void _selectPage(List<Event> events) {
    setState(() {
      _selectionMode = true;
      _allMatching = false;
      _selectedIds
        ..clear()
        ..addAll(events.map((e) => e.id));
    });
  }

  Map<String, dynamic> _selectionFilters() => {
        if (_cameraId != null) 'camera_id': _cameraId,
        if (_acked != null) 'acked': _acked,
      };

  void _selectAllMatching() {
    setState(() {
      _selectionMode = true;
      _allMatching = true;
      _selectedIds.clear();
    });
  }

  Future<void> _downloadSelectedCsv() async {
    final url = ref.read(eventRepoProvider).exportUrl(
          ids: _selectedIds.toList(),
          filters: _allMatching
              ? _selectionFilters().map((k, v) => MapEntry(k, '$v'))
              : null,
        );
    if (!await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication) && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Could not open the event export.')));
    }
  }

  Future<void> _bulkDelete() async {
    if (_selectedIds.isEmpty && !_allMatching) return;
    final ids = _selectedIds.toList(growable: false);
    try {
      final preview = await ref.read(eventRepoProvider).previewBulk(
            ids: ids, allMatching: _allMatching, filters: _selectionFilters());
      if (!mounted) return;
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (ctx) => AlertDialog(
          title: const Text('Delete alerts?'),
          content: Text(
            '${preview.matching} event${preview.matching == 1 ? '' : 's'} from ${_allMatching ? 'all matching filters' : 'this selection'}\n'
            'Linked recordings: ${preview.linkedRecordings} (preserved).\n\n'
            'This cannot be undone.',
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
            FilledButton(
              onPressed: () => Navigator.pop(ctx, true),
              style: FilledButton.styleFrom(backgroundColor: Colors.red),
              child: const Text('Delete'),
            ),
          ],
        ),
      );
      if (confirmed != true) return;
      final result = await ref.read(eventRepoProvider).deleteBulk(
            ids: ids, allMatching: _allMatching, filters: _selectionFilters());
      if (!mounted) return;
      setState(() {
        _clearSelection();
        _resetPaging();
      });
      ref.invalidate(eventsProvider);
      final outcome = StringBuffer(
        'Deleted ${result.deleted} alert${result.deleted == 1 ? '' : 's'}',
      );
      if (result.skipped > 0) {
        outcome.write('; ${result.skipped} skipped');
      }
      if (result.failed > 0) {
        outcome.write('; ${result.failed} failed');
      }
      outcome.write('. Linked recordings were preserved.');
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content: Text(outcome.toString()),
      ));
    } catch (e) {
      if (mounted) _showMutationError(e);
    }
  }

  Future<void> _refresh() async {
    setState(_resetPaging);
    ref.invalidate(eventsProvider);
    await ref.read(eventsProvider(_query).future);
  }

  Future<void> _loadMore() async {
    if (_loadingMore || !_hasMore) return;
    final first = ref.read(eventsProvider(_query)).value;
    if (first == null || first.length < _pageSize) return;
    setState(() => _loadingMore = true);
    try {
      final more = await ref.read(eventRepoProvider).history(
            acked: _acked,
            cameraId: _cameraId,
            limit: _pageSize,
            offset: first.length + _extra.length,
          );
      if (!mounted) return;
      setState(() {
        _extra.addAll(more);
        _hasMore = more.length == _pageSize;
      });
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    } finally {
      if (mounted) setState(() => _loadingMore = false);
    }
  }

  void _afterAck() {
    setState(_resetPaging);
    ref.invalidate(eventsProvider);
    ref.invalidate(unreviewedCountProvider);
  }

  /// Connectivity failures were already queued in the outbox by the
  /// repository, so tell the user the ack will sync rather than that it failed.
  void _showMutationError(Object e) {
    final queued = e is DioException && isConnectivityError(e);
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(
        content:
            Text(queued ? 'Queued — will sync when online' : apiErrorMessage(e))));
  }

  Future<void> _ack(Event event) async {
    try {
      await ref.read(eventRepoProvider).acknowledge(event.id);
      if (mounted) _afterAck();
    } catch (e) {
      if (mounted) _showMutationError(e);
    }
  }

  Future<void> _ackAll(List<Event> visible) async {
    final ids = visible.where((e) => !e.acked).map((e) => e.id).toList();
    if (ids.isEmpty) return;
    try {
      await ref.read(eventRepoProvider).batchAck(ids);
      if (mounted) _afterAck();
    } catch (e) {
      if (mounted) _showMutationError(e);
    }
  }

  @override
  Widget build(BuildContext context) {
    ref.listen(wsMessagesProvider, (_, next) {
      final type = next.value?['type'];
      if (type == 'event' || type == 'event_fired') {
        setState(_resetPaging);
        ref.invalidate(eventsProvider);
      }
    });

    final firstPage = ref.watch(eventsProvider(_query));
    final cameras = ref.watch(camerasProvider).value ?? const <Camera>[];
    final visible = [...?firstPage.value, ..._extra];
    final hasUnacked = visible.any((e) => !e.acked);

    final body = Column(
        children: [
          _filterBar(cameras),
          if (_selectionMode) _selectionBar(visible),
          Expanded(
            child: firstPage.when(
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (e, _) => _ErrorRetry(
                message: apiErrorMessage(e),
                onRetry: () => ref.invalidate(eventsProvider(_query)),
              ),
              data: (items) => _list([...items, ..._extra]),
            ),
          ),
        ],
      );
    if (widget.embedded) return body;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Alerts'),
        actions: [
          if (hasUnacked)
            TextButton(
              onPressed: () => _ackAll(visible),
              child: const Text(
                'Ack all',
                style: TextStyle(
                    color: NurbyColors.accent, fontWeight: FontWeight.w600),
              ),
            ),
        ],
      ),
      body: body,
    );
  }

  Widget _filterBar(List<Camera> cameras) {
    return SizedBox(
      height: 52,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        children: [
          _chip('Unreviewed', _acked == false, () => setState(() {
                _acked = false;
                _clearSelection();
                _resetPaging();
              })),
          _chip('All', _acked == null, () => setState(() {
                _acked = null;
                _clearSelection();
                _resetPaging();
              })),
          Container(
            width: 1,
            margin: const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
            color: NurbyColors.border,
          ),
          const SizedBox(width: 4),
          for (final c in cameras)
            _chip(c.name, _cameraId == c.id, () => setState(() {
                  _cameraId = _cameraId == c.id ? null : c.id;
                  _clearSelection();
                  _resetPaging();
                })),
        ],
      ),
    );
  }

  Widget _selectionBar(List<Event> visible) {
    return Material(
      color: NurbyColors.cardElevated,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 4, 12, 6),
        child: Row(
          children: [
            Text(_allMatching ? 'All matching selected' : '${_selectedIds.length} selected', style: const TextStyle(fontWeight: FontWeight.w600)),
            const Spacer(),
            TextButton(onPressed: () => _selectPage(visible), child: const Text('Select page')),
            if (visible.length >= _pageSize && !_allMatching)
              TextButton(onPressed: _selectAllMatching, child: const Text('All matching')),
            IconButton(
              tooltip: 'Export CSV',
              onPressed: (_selectedIds.isEmpty && !_allMatching) ? null : _downloadSelectedCsv,
              icon: const Icon(Icons.download_outlined),
            ),
            IconButton(
              tooltip: 'Delete selected',
              onPressed: (_selectedIds.isEmpty && !_allMatching) ? null : _bulkDelete,
              icon: const Icon(Icons.delete_outline, color: Colors.redAccent),
            ),
            IconButton(
              tooltip: 'Clear selection',
              onPressed: () => setState(_clearSelection),
              icon: const Icon(Icons.close),
            ),
          ],
        ),
      ),
    );
  }

  Widget _chip(String label, bool selected, VoidCallback onTap) {
    return Padding(
      padding: const EdgeInsets.only(right: 8),
      child: ChoiceChip(
        label: Text(label),
        selected: selected,
        showCheckmark: false,
        selectedColor: NurbyColors.accent.withValues(alpha: 0.15),
        labelStyle: TextStyle(
          fontSize: 13,
          color: selected ? NurbyColors.accent : NurbyColors.foreground,
        ),
        side: BorderSide(
            color: selected ? NurbyColors.accent : NurbyColors.border),
        onSelected: (_) => onTap(),
      ),
    );
  }

  Widget _list(List<Event> events) {
    if (events.isEmpty) {
      return RefreshIndicator(
        onRefresh: _refresh,
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          children: [
            Padding(
              padding: const EdgeInsets.only(top: 96),
              child: Center(
                child: Text(
                  _acked == false ? 'No unreviewed alerts' : 'No alerts yet',
                  style: const TextStyle(color: NurbyColors.mutedForeground),
                ),
              ),
            ),
          ],
        ),
      );
    }

    return RefreshIndicator(
      onRefresh: _refresh,
      child: ListView.builder(
        controller: _scroll,
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(12, 4, 12, 24),
        itemCount: events.length + (_loadingMore ? 1 : 0),
        itemBuilder: (context, i) {
          if (i >= events.length) {
            return const Padding(
              padding: EdgeInsets.all(16),
              child: Center(
                child: SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2)),
              ),
            );
          }
          return _eventRow(events[i]);
        },
      ),
    );
  }

  Color _stripeColor(Event event) {
    if (event.acked) return NurbyColors.border;
    final severity = event.severity?.toLowerCase();
    return (severity == 'alert' || severity == 'high')
        ? NurbyColors.danger
        : NurbyColors.warning;
  }

  Widget _eventRow(Event event) {
    final time = DateFormat('MMM d, HH:mm:ss').format(event.firedAt);
    final status = event.actionStatus != null
        ? ' · ${event.actionType ?? 'action'}: ${event.actionStatus}'
        : '';

    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Card(
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: () => _selectionMode ? _toggleSelected(event.id) : _showDetailSheet(event),
          onLongPress: () => _toggleSelected(event.id),
          child: IntrinsicHeight(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Container(width: 3, color: _stripeColor(event)),
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 12, vertical: 10),
                    child: Row(
                      children: [
                        if (_selectionMode)
                          Padding(
                            padding: const EdgeInsets.only(right: 8),
                            child: Icon(
                              _selectedIds.contains(event.id) ? Icons.check_circle : Icons.radio_button_unchecked,
                              color: _selectedIds.contains(event.id) ? NurbyColors.accent : NurbyColors.mutedForeground,
                            ),
                          ),
                        Expanded(
                          child: Column(
                            mainAxisAlignment: MainAxisAlignment.center,
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                event.ruleName,
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(
                                    fontSize: 14, fontWeight: FontWeight.w600),
                              ),
                              const SizedBox(height: 4),
                              Text('$time$status',
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: monoStyle),
                            ],
                          ),
                        ),
                        if (!event.acked)
                          TextButton(
                            style: TextButton.styleFrom(
                              foregroundColor: NurbyColors.accent,
                              minimumSize: const Size(0, 32),
                              padding: const EdgeInsets.symmetric(
                                  horizontal: 10),
                            ),
                            onPressed: () => _ack(event),
                            child: const Text(
                              'Ack',
                              style: TextStyle(
                                  fontSize: 12.5, fontWeight: FontWeight.w600),
                            ),
                          ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  void _showDetailSheet(Event event) {
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: NurbyColors.card,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(16))),
      isScrollControlled: true,
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: EdgeInsets.fromLTRB(
              20, 18, 20, MediaQuery.of(ctx).viewInsets.bottom + 24),
          child: SingleChildScrollView(
            child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(event.ruleName,
                  style: const TextStyle(
                      fontSize: 16, fontWeight: FontWeight.w600)),
              const SizedBox(height: 14),
              _kv('FIRED',
                  DateFormat('MMM d, yyyy HH:mm:ss').format(event.firedAt)),
              if (event.actionType != null)
                _kv(
                    'ACTION',
                    '${event.actionType}'
                    '${event.actionStatus != null ? ' · ${event.actionStatus}' : ''}'),
              _kv('STATUS', event.acked ? 'acknowledged' : 'unreviewed'),
              const SizedBox(height: 12),
              // Ack says "I saw this". Mute says "stop telling me". On a
              // phone, where the alert actually lands, the second is the
              // more urgent of the two.
              Wrap(
                spacing: 6,
                children: [
                  for (final (d, label) in kMuteChoices)
                    ActionChip(
                      avatar: const Icon(Icons.notifications_off_outlined,
                          size: 14),
                      label: Text(label, style: const TextStyle(fontSize: 12)),
                      onPressed: () {
                        Navigator.pop(ctx);
                        _mute(event, d);
                      },
                    ),
                ],
              ),
              const SizedBox(height: 16),
              // Feedback (#195) asks whether the alert was useful or even
              // correct; notes are the free-text follow-up.
              EventFeedbackPanel(eventId: event.id),
              const SizedBox(height: 16),
              EventNotes(eventId: event.id),
              const SizedBox(height: 16),
              Row(
                children: [
                  if (event.observationId != null) ...[
                    OutlinedButton.icon(
                      icon: const Icon(Icons.image_outlined, size: 18),
                      label: const Text('View sighting'),
                      style: OutlinedButton.styleFrom(
                        foregroundColor: NurbyColors.foreground,
                        side: const BorderSide(color: NurbyColors.border),
                      ),
                      onPressed: () {
                        Navigator.pop(ctx);
                        _showObservationSheet(event.observationId!);
                      },
                    ),
                    const SizedBox(width: 10),
                  ],
                  OutlinedButton.icon(
                    icon: const Icon(Icons.ios_share, size: 18),
                    label: const Text('Share'),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: NurbyColors.foreground,
                      side: const BorderSide(color: NurbyColors.border),
                    ),
                    onPressed: () {
                      Navigator.pop(ctx);
                      showCreateShareSheet(
                        context,
                        kind: 'event',
                        resourceId: event.id,
                        label: event.ruleName,
                      );
                    },
                  ),
                ],
              ),
            ],
          ),
          ),
        ),
      ),
    );
  }

  Future<void> _mute(Event event, Duration d) async {
    try {
      await ref.read(eventRepoProvider).mute(event.id, duration: d);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Muted.')));
      }
    } catch (e) {
      if (mounted) _showMutationError(e);
    }
  }

  Widget _kv(String label, String value) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 72,
            child: Text(
              label,
              style: const TextStyle(
                fontFamily: 'Menlo',
                fontSize: 10,
                letterSpacing: 1.4,
                color: NurbyColors.accent,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
          Expanded(child: Text(value, style: monoStyle)),
        ],
      ),
    );
  }

  void _showObservationSheet(String observationId) {
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: NurbyColors.card,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(16))),
      builder: (ctx) => Consumer(
        builder: (ctx, ref, _) {
          final obsAsync = ref.watch(_observationProvider(observationId));
          return SafeArea(
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
              child: obsAsync.when(
                loading: () => const Padding(
                  padding: EdgeInsets.all(32),
                  child: Center(child: CircularProgressIndicator()),
                ),
                error: (e, _) => Padding(
                  padding: const EdgeInsets.all(16),
                  child: Text(apiErrorMessage(e),
                      style:
                          const TextStyle(color: NurbyColors.mutedForeground)),
                ),
                data: (obs) => Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (obs.thumbnailPath != null) ...[
                      ClipRRect(
                        borderRadius: BorderRadius.circular(12),
                        child: Image.network(
                          ref
                              .read(observationRepoProvider)
                              .thumbnailUrl(obs.id),
                          width: double.infinity,
                          fit: BoxFit.contain,
                          errorBuilder: (_, __, ___) =>
                              const SizedBox.shrink(),
                        ),
                      ),
                      const SizedBox(height: 14),
                    ],
                    Text(
                      obs.vlmDescription ?? 'No description',
                      style: const TextStyle(fontSize: 14, height: 1.4),
                    ),
                    if (obs.labels.isNotEmpty) ...[
                      const SizedBox(height: 12),
                      Wrap(
                        spacing: 6,
                        runSpacing: 6,
                        children: [
                          for (final label in obs.labels)
                            Container(
                              padding: const EdgeInsets.symmetric(
                                  horizontal: 9, vertical: 3),
                              decoration: BoxDecoration(
                                color: NurbyColors.cardElevated,
                                border:
                                    Border.all(color: NurbyColors.border),
                                borderRadius: BorderRadius.circular(20),
                              ),
                              child: Text(
                                label,
                                style: const TextStyle(
                                    fontSize: 11.5,
                                    color: NurbyColors.mutedForeground),
                              ),
                            ),
                        ],
                      ),
                    ],
                    const SizedBox(height: 12),
                    Text(
                      DateFormat('MMM d, yyyy HH:mm:ss').format(obs.startedAt),
                      style: monoStyle,
                    ),
                  ],
                ),
              ),
            ),
          );
        },
      ),
    );
  }
}

class _ErrorRetry extends StatelessWidget {
  const _ErrorRetry({required this.message, required this.onRetry});
  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(message,
              style: const TextStyle(color: NurbyColors.mutedForeground)),
          const SizedBox(height: 12),
          TextButton(onPressed: onRetry, child: const Text('Retry')),
        ],
      ),
    );
  }
}
