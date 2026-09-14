import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:video_player/video_player.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../models/models.dart';
import '../shares/share_sheet.dart';

enum _TimeRange {
  today('Today'),
  week('7d'),
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
      case _TimeRange.all:
        return null;
    }
  }
}

/// Paginated recording browser with an in-app player.
class RecordingsScreen extends ConsumerStatefulWidget {
  const RecordingsScreen({super.key, this.embedded = false});

  /// Rendered inside the Activity screen: no Scaffold, no app bar.
  final bool embedded;

  @override
  ConsumerState<RecordingsScreen> createState() => _RecordingsScreenState();
}

class _RecordingsScreenState extends ConsumerState<RecordingsScreen> {
  static const _pageSize = 50;

  String? _cameraId;
  _TimeRange _range = _TimeRange.all;

  final List<Recording> _items = [];

  /// Per-recording activity, keyed by recording id. Filled a page at a
  /// time after the page itself lands, so the list is never blocked on
  /// it: a row without facets is a row, not a spinner.
  final Map<String, Map<String, dynamic>> _facets = {};
  final _scroll = ScrollController();
  bool _loading = false;
  bool _loadingMore = false;
  bool _hasMore = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _scroll.addListener(_onScroll);
    _load(reset: true);
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  void _onScroll() {
    if (!_scroll.hasClients) return;
    if (_scroll.position.pixels >
        _scroll.position.maxScrollExtent - 400) {
      _load();
    }
  }

  Future<void> _load({bool reset = false}) async {
    if (reset) {
      setState(() {
        _loading = _items.isEmpty;
        _error = null;
        _hasMore = true;
      });
    } else {
      if (_loading || _loadingMore || !_hasMore) return;
      setState(() => _loadingMore = true);
    }
    final offset = reset ? 0 : _items.length;
    try {
      final page = await ref.read(recordingRepoProvider).list(
            cameraId: _cameraId,
            from: _range.start,
            limit: _pageSize,
            offset: offset,
          );
      if (!mounted) return;
      setState(() {
        if (reset) {
          _items.clear();
          _facets.clear();
        }
        _items.addAll(page);
        _hasMore = page.length == _pageSize;
        _loading = false;
        _loadingMore = false;
      });
      _loadFacets([for (final r in page) r.id]);
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _loadingMore = false;
        if (reset && _items.isEmpty) _error = apiErrorMessage(e);
      });
    }
  }

  void _onFilterChanged() {
    setState(() => _items.clear());
    _load(reset: true);
  }

  @override
  Widget build(BuildContext context) {
    final cameras = ref.watch(camerasProvider).value ?? const <Camera>[];
    final cameraNames = {for (final c in cameras) c.id: c.name};

    final body = Column(
        children: [
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
            child: Row(
              children: [
                _CameraFilterChip(
                  cameras: cameras,
                  selectedId: _cameraId,
                  onSelected: (id) {
                    _cameraId = id;
                    _onFilterChanged();
                  },
                ),
                const SizedBox(width: 8),
                for (final r in _TimeRange.values) ...[
                  ChoiceChip(
                    label: Text(r.label),
                    selected: _range == r,
                    selectedColor: NurbyColors.accent.withValues(alpha: 0.18),
                    onSelected: (_) {
                      _range = r;
                      _onFilterChanged();
                    },
                  ),
                  const SizedBox(width: 8),
                ],
              ],
            ),
          ),
          Expanded(child: _body(cameraNames)),
        ],
      );
    if (widget.embedded) return body;
    return Scaffold(
      appBar: AppBar(title: const Text('Recordings')),
      body: body,
    );
  }

  Widget _body(Map<String, String> cameraNames) {
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
            TextButton(
                onPressed: () => _load(reset: true),
                child: const Text('Retry')),
          ],
        ),
      );
    }
    if (_items.isEmpty) {
      return RefreshIndicator(
        onRefresh: () => _load(reset: true),
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          children: const [
            SizedBox(height: 120),
            Icon(Icons.video_library_outlined,
                size: 44, color: NurbyColors.mutedForeground),
            SizedBox(height: 14),
            Center(
              child: Text('No recordings',
                  style:
                      TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
            ),
            SizedBox(height: 6),
            Center(
              child: Text(
                'Enable recording on a camera to capture footage.',
                textAlign: TextAlign.center,
                style: TextStyle(
                    color: NurbyColors.mutedForeground, fontSize: 13),
              ),
            ),
          ],
        ),
      );
    }
    return RefreshIndicator(
      onRefresh: () => _load(reset: true),
      child: ListView.separated(
        controller: _scroll,
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 24),
        itemCount: _items.length + (_loadingMore ? 1 : 0),
        separatorBuilder: (_, __) => const SizedBox(height: 8),
        itemBuilder: (context, i) {
          if (i >= _items.length) {
            return const Center(
              child: Padding(
                padding: EdgeInsets.all(12),
                child: SizedBox(
                  width: 20,
                  height: 20,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
              ),
            );
          }
          final rec = _items[i];
          final cameraName = cameraNames[rec.cameraId] ?? 'Camera';
          return _RecordingRow(
            recording: rec,
            cameraName: cameraName,
            facets: _facets[rec.id],
            thumbnailUrl: ref.read(recordingRepoProvider).thumbnailUrl(rec.id),
            onTap: () => _openPlayer(rec, cameraName),
            onLongPress: () => _showActions(rec, cameraName),
          );
        },
      ),
    );
  }

  Future<void> _loadFacets(List<String> ids) async {
    try {
      final f = await ref.read(recordingRepoProvider).facets(ids);
      if (mounted) setState(() => _facets.addAll(f));
    } catch (_) {
      // Facets are decoration. A failure here must not surface as an
      // error on a list that is otherwise fine.
    }
  }

  void _showActions(Recording rec, String cameraName) {
    final repo = ref.read(recordingRepoProvider);
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: NurbyColors.cardElevated,
      builder: (ctx) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.ios_share),
              title: const Text('Share a link'),
              onTap: () {
                Navigator.pop(ctx);
                _shareRecording(rec, cameraName);
              },
            ),
            ListTile(
              leading: const Icon(Icons.download_outlined),
              title: const Text('Download the whole file'),
              subtitle: Text(_size(rec), style: const TextStyle(fontSize: 12)),
              onTap: () {
                Navigator.pop(ctx);
                _download(repo.downloadUrl(rec.id));
              },
            ),
            ListTile(
              leading: const Icon(Icons.content_cut),
              title: const Text('Download a clip'),
              subtitle: const Text('Pick a start and end',
                  style: TextStyle(fontSize: 12)),
              onTap: () {
                Navigator.pop(ctx);
                _pickClip(rec);
              },
            ),
          ],
        ),
      ),
    );
  }

  static String _size(Recording rec) {
    final b = rec.fileSizeBytes;
    return b == null ? '' : '${(b / (1024 * 1024)).toStringAsFixed(1)} MB';
  }

  /// Hand the URL to the OS. Where the file ends up is the platform's
  /// business: on iOS that is Files, on Android the Downloads folder.
  /// The app deliberately does not try to own that.
  Future<void> _download(String url) async {
    final uri = Uri.parse(url);
    if (!await launchUrl(uri, mode: LaunchMode.externalApplication)) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            const SnackBar(content: Text('Nothing on this device could open that.')));
      }
    }
  }

  Future<void> _pickClip(Recording rec) async {
    final total = rec.durationSeconds?.round() ?? 0;
    if (total < 2) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('That recording is too short to clip.')));
      return;
    }
    final range = await showDialog<RangeValues>(
      context: context,
      builder: (ctx) => _ClipDialog(totalSeconds: total),
    );
    if (range == null) return;
    _download(ref.read(recordingRepoProvider).clipUrl(
          rec.id,
          start: Duration(seconds: range.start.round()),
          end: Duration(seconds: range.end.round()),
        ));
  }

  void _shareRecording(Recording rec, String cameraName) {
    showCreateShareSheet(
      context,
      kind: 'recording',
      resourceId: rec.id,
      label:
          '$cameraName · ${DateFormat('MMM d, HH:mm').format(rec.startedAt)}',
    );
  }

  void _openPlayer(Recording rec, String cameraName) {
    final url = ref.read(recordingRepoProvider).streamUrl(rec.id);
    Navigator.of(context).push(MaterialPageRoute<void>(
      builder: (_) => _RecordingPlayerPage(
        url: url,
        title: cameraName,
        subtitle: DateFormat('EEE, MMM d y · HH:mm').format(rec.startedAt),
        onShare: () => _shareRecording(rec, cameraName),
      ),
    ));
  }
}

class _RecordingRow extends StatelessWidget {
  const _RecordingRow({
    required this.recording,
    required this.cameraName,
    required this.onTap,
    required this.onLongPress,
    this.facets,
    this.thumbnailUrl,
  });

  final Recording recording;
  final String cameraName;
  final Map<String, dynamic>? facets;
  final String? thumbnailUrl;

  /// One line saying what was in it. Empty when facets have not landed
  /// or found nothing, and the row simply has no such line.
  String get _activity {
    final f = facets;
    if (f == null) return '';
    final parts = <String>[
      ...(f['persons'] as List? ?? const []).map((p) => '$p'),
      ...(f['objects'] as List? ?? const []).map((o) => '$o'),
      ...(f['vehicles'] as List? ?? const []).map((v) => '$v'),
    ];
    if (f['has_audio'] == true) parts.add('speech');
    return parts.join(', ');
  }
  final VoidCallback onTap;
  final VoidCallback onLongPress;

  String get _duration {
    final secs = recording.durationSeconds;
    if (secs == null) return '--:--';
    final d = Duration(seconds: secs.round());
    final m = d.inMinutes.toString().padLeft(2, '0');
    final s = (d.inSeconds % 60).toString().padLeft(2, '0');
    return '$m:$s';
  }

  String get _size {
    final bytes = recording.fileSizeBytes;
    if (bytes == null) return '';
    return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
  }

  @override
  Widget build(BuildContext context) {
    return Card(
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        onLongPress: onLongPress,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          child: Row(
            children: [
              ClipRRect(
                borderRadius: BorderRadius.circular(10),
                child: SizedBox(
                  width: 64,
                  height: 42,
                  child: thumbnailUrl == null
                      ? const _PlayGlyph()
                      : Image.network(
                          thumbnailUrl!,
                          fit: BoxFit.cover,
                          // No thumbnail is normal for a recording still
                          // being written. Fall back to the glyph rather
                          // than a broken-image icon.
                          errorBuilder: (_, __, ___) => const _PlayGlyph(),
                        ),
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(cameraName,
                        style: const TextStyle(
                            fontWeight: FontWeight.w600, fontSize: 14),
                        overflow: TextOverflow.ellipsis),
                    const SizedBox(height: 3),
                    Text(
                      DateFormat('MMM d y · HH:mm:ss')
                          .format(recording.startedAt),
                      style: monoStyle,
                    ),
                    if (_activity.isNotEmpty) ...[
                      const SizedBox(height: 3),
                      Text(_activity,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                              fontSize: 11,
                              color: NurbyColors.mutedForeground)),
                    ],
                  ],
                ),
              ),
              const SizedBox(width: 8),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Text(_duration,
                      style: monoStyle.copyWith(
                          color: NurbyColors.foreground)),
                  const SizedBox(height: 3),
                  Text(_size, style: monoStyle.copyWith(fontSize: 10.5)),
                ],
              ),
            ],
          ),
        ),
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

/// Full-screen playback for a single recording. The stream URL already
/// carries ?token= (native players cannot send Authorization headers).
class _RecordingPlayerPage extends StatefulWidget {
  const _RecordingPlayerPage({
    required this.url,
    required this.title,
    required this.subtitle,
    required this.onShare,
  });

  final String url;
  final String title;
  final String subtitle;
  final VoidCallback onShare;

  @override
  State<_RecordingPlayerPage> createState() => _RecordingPlayerPageState();
}

class _RecordingPlayerPageState extends State<_RecordingPlayerPage> {
  late final VideoPlayerController _controller;
  String? _error;

  @override
  void initState() {
    super.initState();
    _controller = VideoPlayerController.networkUrl(Uri.parse(widget.url));
    _controller.initialize().then((_) {
      if (!mounted) return;
      setState(() {});
      _controller.play();
    }).catchError((Object e) {
      if (!mounted) return;
      setState(() => _error = 'Could not load video');
    });
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  String _fmt(Duration d) {
    final m = d.inMinutes.toString().padLeft(2, '0');
    final s = (d.inSeconds % 60).toString().padLeft(2, '0');
    return '$m:$s';
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: Colors.black,
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(widget.title, style: const TextStyle(fontSize: 16)),
            Text(widget.subtitle, style: monoStyle.copyWith(fontSize: 11)),
          ],
        ),
        actions: [
          IconButton(
            tooltip: 'Share link',
            icon: const Icon(Icons.ios_share, size: 22),
            onPressed: widget.onShare,
          ),
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: Center(
              child: _error != null
                  ? Text(_error!,
                      style:
                          const TextStyle(color: NurbyColors.mutedForeground))
                  : _controller.value.isInitialized
                      ? AspectRatio(
                          aspectRatio: _controller.value.aspectRatio,
                          child: VideoPlayer(_controller),
                        )
                      : const CircularProgressIndicator(),
            ),
          ),
          if (_error == null)
            ValueListenableBuilder<VideoPlayerValue>(
              valueListenable: _controller,
              builder: (context, value, _) {
                return SafeArea(
                  top: false,
                  child: Container(
                    color: NurbyColors.background,
                    padding: const EdgeInsets.fromLTRB(8, 4, 8, 8),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        VideoProgressIndicator(
                          _controller,
                          allowScrubbing: true,
                          padding: const EdgeInsets.symmetric(
                              horizontal: 4, vertical: 8),
                          colors: const VideoProgressColors(
                            playedColor: NurbyColors.accent,
                            bufferedColor: NurbyColors.border,
                            backgroundColor: NurbyColors.cardElevated,
                          ),
                        ),
                        Row(
                          children: [
                            IconButton(
                              iconSize: 32,
                              color: NurbyColors.foreground,
                              icon: Icon(value.isPlaying
                                  ? Icons.pause_circle_filled
                                  : Icons.play_circle_filled),
                              onPressed: !value.isInitialized
                                  ? null
                                  : () {
                                      value.isPlaying
                                          ? _controller.pause()
                                          : _controller.play();
                                    },
                            ),
                            const Spacer(),
                            Text(
                              '${_fmt(value.position)} / ${_fmt(value.duration)}',
                              style: monoStyle,
                            ),
                            const SizedBox(width: 8),
                          ],
                        ),
                      ],
                    ),
                  ),
                );
              },
            ),
        ],
      ),
    );
  }
}


class _PlayGlyph extends StatelessWidget {
  const _PlayGlyph();

  @override
  Widget build(BuildContext context) => Container(
        decoration: BoxDecoration(
          color: NurbyColors.cardElevated,
          border: Border.all(color: NurbyColors.border),
          borderRadius: BorderRadius.circular(10),
        ),
        child: const Icon(Icons.play_arrow,
            color: NurbyColors.accent, size: 22),
      );
}

/// Pick a start and end inside a recording.
class _ClipDialog extends StatefulWidget {
  const _ClipDialog({required this.totalSeconds});

  final int totalSeconds;

  @override
  State<_ClipDialog> createState() => _ClipDialogState();
}

class _ClipDialogState extends State<_ClipDialog> {
  late RangeValues _range =
      RangeValues(0, widget.totalSeconds.clamp(1, 60).toDouble());

  String _fmt(double s) {
    final d = Duration(seconds: s.round());
    return '${d.inMinutes.toString().padLeft(2, '0')}:'
        '${(d.inSeconds % 60).toString().padLeft(2, '0')}';
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
        backgroundColor: NurbyColors.cardElevated,
        title: const Text('Clip'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('${_fmt(_range.start)} to ${_fmt(_range.end)}',
                style: const TextStyle(fontFamily: 'Menlo')),
            RangeSlider(
              values: _range,
              min: 0,
              max: widget.totalSeconds.toDouble(),
              activeColor: NurbyColors.accent,
              onChanged: (v) {
                // Keep at least a second between the handles, or the
                // server is asked for an empty clip.
                if (v.end - v.start < 1) return;
                setState(() => _range = v);
              },
            ),
          ],
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('Cancel')),
          FilledButton(
              onPressed: () => Navigator.pop(context, _range),
              child: const Text('Download')),
        ],
      );
}
