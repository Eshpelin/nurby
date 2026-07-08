import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../models/models.dart';

const _pageSize = 50;

typedef _TimelineQuery = ({String? cameraId, int days});

/// 0 = start of today, otherwise a rolling window of [days] days.
DateTime _fromFor(int days) {
  final now = DateTime.now();
  return days == 0
      ? DateTime(now.year, now.month, now.day)
      : now.subtract(Duration(days: days));
}

/// First page of the merged observation/transcript timeline per filter.
final _timelineProvider =
    FutureProvider.family<List<TimelineItem>, _TimelineQuery>(
        (ref, q) => ref.watch(timelineRepoProvider).list(
              cameraId: q.cameraId,
              from: _fromFor(q.days),
              limit: _pageSize,
            ));

/// Timeline tab: merged activity feed grouped under hour headers,
/// mirroring the web dashboard.
class TimelineScreen extends ConsumerStatefulWidget {
  const TimelineScreen({super.key});

  @override
  ConsumerState<TimelineScreen> createState() => _TimelineScreenState();
}

class _TimelineScreenState extends ConsumerState<TimelineScreen> {
  final _scroll = ScrollController();
  final List<TimelineItem> _extra = [];
  String? _cameraId;
  int _days = 0; // 0 = today, 7 = 7d, 30 = 30d
  bool _loadingMore = false;
  bool _hasMore = true;

  _TimelineQuery get _query => (cameraId: _cameraId, days: _days);

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

  void _setCamera(String? id) => setState(() {
        _cameraId = id;
        _resetPaging();
      });

  void _setDays(int days) => setState(() {
        _days = days;
        _resetPaging();
      });

  Future<void> _refresh() async {
    setState(_resetPaging);
    ref.invalidate(_timelineProvider);
    await ref.read(_timelineProvider(_query).future);
  }

  Future<void> _loadMore() async {
    if (_loadingMore || !_hasMore) return;
    final first = ref.read(_timelineProvider(_query)).value;
    if (first == null || first.length < _pageSize) return;
    setState(() => _loadingMore = true);
    try {
      final more = await ref.read(timelineRepoProvider).list(
            cameraId: _cameraId,
            from: _fromFor(_days),
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

  @override
  Widget build(BuildContext context) {
    ref.listen(wsMessagesProvider, (_, next) {
      const types = {
        'event',
        'notification',
        'transcript_created',
        'summary_created',
      };
      if (types.contains(next.value?['type'])) {
        setState(_resetPaging);
        ref.invalidate(_timelineProvider);
      }
    });

    final firstPage = ref.watch(_timelineProvider(_query));
    final cameras = ref.watch(camerasProvider).value ?? const <Camera>[];
    final cameraNames = {for (final c in cameras) c.id: c.name};

    return Scaffold(
      appBar: AppBar(title: const Text('Timeline')),
      body: Column(
        children: [
          _filterBar(cameras),
          Expanded(
            child: firstPage.when(
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (e, _) => _ErrorRetry(
                message: apiErrorMessage(e),
                onRetry: () => ref.invalidate(_timelineProvider(_query)),
              ),
              data: (items) => _list(items, cameraNames),
            ),
          ),
        ],
      ),
    );
  }

  Widget _filterBar(List<Camera> cameras) {
    return SizedBox(
      height: 52,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        children: [
          _chip('All cameras', _cameraId == null, () => _setCamera(null)),
          for (final c in cameras)
            _chip(c.name, _cameraId == c.id, () => _setCamera(c.id)),
          Container(
            width: 1,
            margin: const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
            color: NurbyColors.border,
          ),
          const SizedBox(width: 4),
          _chip('Today', _days == 0, () => _setDays(0)),
          _chip('7d', _days == 7, () => _setDays(7)),
          _chip('30d', _days == 30, () => _setDays(30)),
        ],
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

  Widget _list(List<TimelineItem> firstPage, Map<String, String> names) {
    final all = [...firstPage, ..._extra];
    if (all.isEmpty) {
      return RefreshIndicator(
        onRefresh: _refresh,
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          children: const [
            Padding(
              padding: EdgeInsets.only(top: 96),
              child: Center(
                child: Text('No activity in this period',
                    style: TextStyle(color: NurbyColors.mutedForeground)),
              ),
            ),
          ],
        ),
      );
    }

    // Flatten into [DateTime header, item, item, DateTime header, ...].
    final entries = <Object>[];
    String? lastKey;
    for (final item in all) {
      final t = item.startedAt;
      final key = '${t.year}-${t.month}-${t.day}-${t.hour}';
      if (key != lastKey) {
        entries.add(t);
        lastKey = key;
      }
      entries.add(item);
    }

    return RefreshIndicator(
      onRefresh: _refresh,
      child: ListView.builder(
        controller: _scroll,
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(12, 0, 12, 24),
        itemCount: entries.length + (_loadingMore ? 1 : 0),
        itemBuilder: (context, i) {
          if (i >= entries.length) {
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
          final entry = entries[i];
          if (entry is DateTime) return _hourHeader(entry);
          return _itemRow(entry as TimelineItem, names);
        },
      ),
    );
  }

  Widget _hourHeader(DateTime t) {
    final now = DateTime.now();
    final sameDay =
        t.year == now.year && t.month == now.month && t.day == now.day;
    final label = sameDay
        ? DateFormat('HH:00').format(t)
        : '${DateFormat('MMM d').format(t).toUpperCase()} · ${DateFormat('HH:00').format(t)}';
    return Padding(
      padding: const EdgeInsets.only(top: 16, bottom: 8, left: 4),
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
    );
  }

  Widget _itemRow(TimelineItem item, Map<String, String> names) {
    final isObservation = item.kind == 'observation';
    final text = item.text?.trim();
    final display = (text == null || text.isEmpty)
        ? (isObservation
            ? (item.observation?.labels.join(', ') ?? 'Observation')
            : 'Transcript')
        : text;

    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Card(
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: isObservation ? () => _showObservationSheet(item, names) : null,
          child: Padding(
            padding: const EdgeInsets.all(10),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                _thumb(item),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        display,
                        maxLines: 3,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontSize: 13, height: 1.35),
                      ),
                      const SizedBox(height: 6),
                      Text(
                        '${DateFormat('HH:mm:ss').format(item.startedAt)} · ${names[item.cameraId] ?? 'Camera'}',
                        style: monoStyle,
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _thumb(TimelineItem item) {
    if (item.kind == 'observation' && item.thumbnailPath != null) {
      return ClipRRect(
        borderRadius: BorderRadius.circular(6),
        child: Image.network(
          ref.read(observationRepoProvider).thumbnailUrl(item.id),
          width: 74,
          height: 52,
          fit: BoxFit.cover,
          errorBuilder: (_, __, ___) => _iconBox(Icons.image_outlined),
        ),
      );
    }
    return _iconBox(
        item.kind == 'transcript' ? Icons.mic : Icons.image_outlined);
  }

  Widget _iconBox(IconData icon) {
    return Container(
      width: 74,
      height: 52,
      decoration: BoxDecoration(
        color: NurbyColors.cardElevated,
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: NurbyColors.borderSubtle),
      ),
      child: Icon(icon, size: 18, color: NurbyColors.mutedForeground),
    );
  }

  void _showObservationSheet(TimelineItem item, Map<String, String> names) {
    final obs = item.observation;
    final thumbUrl = item.thumbnailPath != null
        ? ref.read(observationRepoProvider).thumbnailUrl(item.id)
        : null;
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: NurbyColors.card,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(16))),
      builder: (ctx) => SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (thumbUrl != null) ...[
                ClipRRect(
                  borderRadius: BorderRadius.circular(12),
                  child: Image.network(
                    thumbUrl,
                    width: double.infinity,
                    fit: BoxFit.contain,
                    errorBuilder: (_, __, ___) => const SizedBox.shrink(),
                  ),
                ),
                const SizedBox(height: 14),
              ],
              Text(
                item.text ?? 'No description',
                style: const TextStyle(fontSize: 14, height: 1.4),
              ),
              if (obs != null && obs.labels.isNotEmpty) ...[
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
                          border: Border.all(color: NurbyColors.border),
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
                '${DateFormat('MMM d, yyyy HH:mm:ss').format(item.startedAt)} · ${names[item.cameraId] ?? 'Camera'}',
                style: monoStyle,
              ),
            ],
          ),
        ),
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
