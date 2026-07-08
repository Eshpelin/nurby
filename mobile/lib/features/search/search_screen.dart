import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../models/models.dart';

enum _TimeRange {
  today('Today'),
  week('7d'),
  month('30d'),
  all('All');

  const _TimeRange(this.label);
  final String label;

  DateTime? get start {
    final now = DateTime.now();
    switch (this) {
      case _TimeRange.today:
        return DateTime(now.year, now.month, now.day);
      case _TimeRange.week:
        return now.subtract(const Duration(days: 7));
      case _TimeRange.month:
        return now.subtract(const Duration(days: 30));
      case _TimeRange.all:
        return null;
    }
  }
}

/// Semantic search over observations, plus a one-shot AI answer card.
class SearchScreen extends ConsumerStatefulWidget {
  const SearchScreen({super.key});

  @override
  ConsumerState<SearchScreen> createState() => _SearchScreenState();
}

class _SearchScreenState extends ConsumerState<SearchScreen> {
  final _controller = TextEditingController();

  String _query = '';
  String? _cameraId;
  _TimeRange _range = _TimeRange.all;

  bool _loading = false;
  bool _searched = false;
  String? _error;
  List<Observation> _results = const [];

  bool _askLoading = false;
  String? _askAnswer;
  String? _askNote;

  /// Guards against stale async results after a newer search fires.
  int _seq = 0;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  List<Observation> get _filtered {
    final start = _range.start;
    if (start == null) return _results;
    return _results.where((o) => o.startedAt.isAfter(start)).toList();
  }

  void _submit(String raw) {
    final q = raw.trim();
    if (q.isEmpty) return;
    _query = q;
    _runSearch();
  }

  Future<void> _runSearch() async {
    if (_query.isEmpty) return;
    final seq = ++_seq;
    setState(() {
      _loading = true;
      _error = null;
      _askLoading = true;
      _askAnswer = null;
      _askNote = null;
    });
    try {
      final results = await ref
          .read(searchRepoProvider)
          .search(_query, cameraId: _cameraId);
      if (!mounted || seq != _seq) return;
      setState(() {
        _results = results;
        _loading = false;
        _searched = true;
      });
      // Fire the AI answer only after the search itself completed.
      _runAsk(_query, seq);
    } catch (e) {
      if (!mounted || seq != _seq) return;
      setState(() {
        _loading = false;
        _searched = true;
        _askLoading = false;
        _error = apiErrorMessage(e);
      });
    }
  }

  Future<void> _runAsk(String question, int seq) async {
    try {
      final j = await ref.read(searchRepoProvider).ask(question);
      if (!mounted || seq != _seq) return;
      setState(() {
        _askLoading = false;
        _askAnswer = j['answer'] as String?;
        _askNote = j['note'] as String?;
      });
    } catch (_) {
      // Soft-fail: just hide the AI card.
      if (!mounted || seq != _seq) return;
      setState(() => _askLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final cameras = ref.watch(camerasProvider).value ?? const <Camera>[];

    return Scaffold(
      appBar: AppBar(title: const Text('Search')),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 4, 12, 8),
            child: TextField(
              controller: _controller,
              textInputAction: TextInputAction.search,
              onSubmitted: _submit,
              decoration: InputDecoration(
                hintText: 'Search footage, e.g. "person with a package"',
                prefixIcon: const Icon(Icons.search,
                    color: NurbyColors.mutedForeground),
                suffixIcon: IconButton(
                  icon: const Icon(Icons.arrow_forward,
                      color: NurbyColors.accent),
                  onPressed: () => _submit(_controller.text),
                ),
              ),
            ),
          ),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 12),
            child: Row(
              children: [
                _CameraFilterChip(
                  cameras: cameras,
                  selectedId: _cameraId,
                  onSelected: (id) {
                    setState(() => _cameraId = id);
                    // Camera is a server-side filter; re-run the search.
                    if (_searched) _runSearch();
                  },
                ),
                const SizedBox(width: 8),
                for (final r in _TimeRange.values) ...[
                  ChoiceChip(
                    label: Text(r.label),
                    selected: _range == r,
                    selectedColor: NurbyColors.accent.withValues(alpha: 0.18),
                    onSelected: (_) => setState(() => _range = r),
                  ),
                  const SizedBox(width: 8),
                ],
              ],
            ),
          ),
          const SizedBox(height: 8),
          Expanded(child: _body()),
        ],
      ),
    );
  }

  Widget _body() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(_error!,
                style: const TextStyle(color: NurbyColors.mutedForeground)),
            const SizedBox(height: 12),
            TextButton(onPressed: _runSearch, child: const Text('Retry')),
          ],
        ),
      );
    }
    if (!_searched) {
      return const _EmptyHint(
        icon: Icons.manage_search,
        title: 'Search your footage',
        subtitle:
            'Describe what you are looking for in plain language.\nNurby searches every observation.',
      );
    }

    final results = _filtered;
    final showAiCard = _askLoading ||
        (_askAnswer != null && _askAnswer!.trim().isNotEmpty);

    return CustomScrollView(
      slivers: [
        if (showAiCard)
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
              child: _AiAnswerCard(
                loading: _askLoading,
                answer: _askAnswer,
                note: _askNote,
              ),
            ),
          ),
        if (results.isEmpty)
          const SliverFillRemaining(
            hasScrollBody: false,
            child: _EmptyHint(
              icon: Icons.search_off,
              title: 'No results',
              subtitle: 'Try different words or a wider time range.',
            ),
          )
        else
          SliverPadding(
            padding: const EdgeInsets.fromLTRB(12, 0, 12, 24),
            sliver: SliverGrid(
              gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                crossAxisCount: 2,
                mainAxisSpacing: 12,
                crossAxisSpacing: 12,
                childAspectRatio: 0.95,
              ),
              delegate: SliverChildBuilderDelegate(
                (context, i) => _ResultCard(
                  observation: results[i],
                  onTap: () => _showDetail(results[i]),
                ),
                childCount: results.length,
              ),
            ),
          ),
      ],
    );
  }

  void _showDetail(Observation o) {
    final thumbUrl = ref.read(observationRepoProvider).thumbnailUrl(o.id);
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: NurbyColors.card,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      builder: (context) => SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Center(
                child: Container(
                  width: 36,
                  height: 4,
                  margin: const EdgeInsets.only(bottom: 14),
                  decoration: BoxDecoration(
                    color: NurbyColors.border,
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
              ),
              ClipRRect(
                borderRadius: BorderRadius.circular(12),
                child: AspectRatio(
                  aspectRatio: 16 / 9,
                  child: _Thumbnail(url: thumbUrl),
                ),
              ),
              const SizedBox(height: 14),
              Text(
                o.vlmDescription ?? 'No description',
                style: const TextStyle(fontSize: 14, height: 1.4),
              ),
              if (o.labels.isNotEmpty) ...[
                const SizedBox(height: 12),
                Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  children: [
                    for (final label in o.labels)
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 9, vertical: 3),
                        decoration: BoxDecoration(
                          color: NurbyColors.cardElevated,
                          border: Border.all(color: NurbyColors.border),
                          borderRadius: BorderRadius.circular(999),
                        ),
                        child: Text(label,
                            style: monoStyle.copyWith(fontSize: 11)),
                      ),
                  ],
                ),
              ],
              const SizedBox(height: 12),
              Text(
                DateFormat('EEE, MMM d y · HH:mm:ss').format(o.startedAt),
                style: monoStyle,
              ),
              const SizedBox(height: 8),
            ],
          ),
        ),
      ),
    );
  }
}

class _ResultCard extends StatelessWidget {
  const _ResultCard({required this.observation, required this.onTap});
  final Observation observation;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Consumer(builder: (context, ref, _) {
      final thumbUrl =
          ref.read(observationRepoProvider).thumbnailUrl(observation.id);
      return GestureDetector(
        onTap: onTap,
        child: Container(
          decoration: BoxDecoration(
            color: NurbyColors.card,
            border: Border.all(color: NurbyColors.border),
            borderRadius: BorderRadius.circular(12),
          ),
          clipBehavior: Clip.antiAlias,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              AspectRatio(
                aspectRatio: 16 / 9,
                child: _Thumbnail(url: thumbUrl),
              ),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.all(8),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(
                        observation.vlmDescription ?? 'No description',
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontSize: 12, height: 1.3),
                      ),
                      Text(
                        DateFormat('MMM d · HH:mm')
                            .format(observation.startedAt),
                        style: monoStyle.copyWith(fontSize: 10.5),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      );
    });
  }
}

class _Thumbnail extends StatelessWidget {
  const _Thumbnail({required this.url});
  final String url;

  @override
  Widget build(BuildContext context) {
    return Container(
      color: NurbyColors.cardElevated,
      child: Image.network(
        url,
        fit: BoxFit.cover,
        errorBuilder: (_, __, ___) => const Center(
          child: Icon(Icons.image_not_supported_outlined,
              size: 24, color: NurbyColors.mutedForeground),
        ),
      ),
    );
  }
}

class _AiAnswerCard extends StatelessWidget {
  const _AiAnswerCard({required this.loading, this.answer, this.note});
  final bool loading;
  final String? answer;
  final String? note;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: NurbyColors.card,
        border: Border.all(color: NurbyColors.border),
        borderRadius: BorderRadius.circular(12),
      ),
      clipBehavior: Clip.antiAlias,
      child: IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Container(width: 3, color: NurbyColors.accent),
            Expanded(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        const Icon(Icons.auto_awesome,
                            size: 14, color: NurbyColors.accent),
                        const SizedBox(width: 6),
                        Text('AI ANSWER',
                            style: monoStyle.copyWith(
                              fontSize: 10.5,
                              letterSpacing: 1,
                              color: NurbyColors.accent,
                            )),
                      ],
                    ),
                    const SizedBox(height: 10),
                    if (loading)
                      const _AnswerShimmer()
                    else ...[
                      Text(answer ?? '',
                          style: const TextStyle(fontSize: 13.5, height: 1.45)),
                      if (note != null && note!.trim().isNotEmpty) ...[
                        const SizedBox(height: 8),
                        Text(note!,
                            style: const TextStyle(
                                fontSize: 12,
                                color: NurbyColors.mutedForeground)),
                      ],
                    ],
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _AnswerShimmer extends StatefulWidget {
  const _AnswerShimmer();

  @override
  State<_AnswerShimmer> createState() => _AnswerShimmerState();
}

class _AnswerShimmerState extends State<_AnswerShimmer>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 850),
  )..repeat(reverse: true);

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Widget _bar(double? width) => Container(
        height: 11,
        width: width,
        decoration: BoxDecoration(
          color: NurbyColors.border,
          borderRadius: BorderRadius.circular(5),
        ),
      );

  @override
  Widget build(BuildContext context) {
    return FadeTransition(
      opacity: Tween<double>(begin: 0.35, end: 1).animate(_controller),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _bar(double.infinity),
          const SizedBox(height: 7),
          _bar(210),
          const SizedBox(height: 7),
          _bar(130),
        ],
      ),
    );
  }
}

class _CameraFilterChip extends StatelessWidget {
  const _CameraFilterChip({
    required this.cameras,
    required this.selectedId,
    required this.onSelected,
  });

  final List<Camera> cameras;
  final String? selectedId;
  final ValueChanged<String?> onSelected;

  @override
  Widget build(BuildContext context) {
    var name = 'All cameras';
    for (final c in cameras) {
      if (c.id == selectedId) name = c.name;
    }
    return PopupMenuButton<String>(
      color: NurbyColors.cardElevated,
      onSelected: (v) => onSelected(v.isEmpty ? null : v),
      itemBuilder: (_) => [
        const PopupMenuItem(value: '', child: Text('All cameras')),
        for (final c in cameras)
          PopupMenuItem(value: c.id, child: Text(c.name)),
      ],
      child: Chip(
        avatar: Icon(
          Icons.videocam_outlined,
          size: 16,
          color: selectedId != null
              ? NurbyColors.accent
              : NurbyColors.mutedForeground,
        ),
        label: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(name, style: const TextStyle(fontSize: 13)),
            const Icon(Icons.arrow_drop_down,
                size: 18, color: NurbyColors.mutedForeground),
          ],
        ),
      ),
    );
  }
}

class _EmptyHint extends StatelessWidget {
  const _EmptyHint({
    required this.icon,
    required this.title,
    required this.subtitle,
  });

  final IconData icon;
  final String title;
  final String subtitle;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 44, color: NurbyColors.mutedForeground),
            const SizedBox(height: 14),
            Text(title,
                style: const TextStyle(
                    fontSize: 16, fontWeight: FontWeight.w600)),
            const SizedBox(height: 6),
            Text(
              subtitle,
              textAlign: TextAlign.center,
              style: const TextStyle(
                  color: NurbyColors.mutedForeground, fontSize: 13),
            ),
          ],
        ),
      ),
    );
  }
}
