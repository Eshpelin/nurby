import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:share_plus/share_plus.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../models/models.dart';

/// Opens the two-step "create share link" bottom sheet for one resource:
/// pick expiry + optional view cap, create, then share/copy the public URL.
Future<void> showCreateShareSheet(
  BuildContext context, {
  required String kind, // recording | observation | event
  required String resourceId,
  String? label,
}) {
  return showModalBottomSheet<void>(
    context: context,
    backgroundColor: NurbyColors.card,
    isScrollControlled: true,
    shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16))),
    builder: (_) => Padding(
      padding:
          EdgeInsets.only(bottom: MediaQuery.of(context).viewInsets.bottom),
      child: _CreateShareSheet(kind: kind, resourceId: resourceId, label: label),
    ),
  );
}

/// Expiry presets. The backend granularity is whole days (1..30), so the
/// hour-level choices round up to a 1-day link; the label says so.
enum _Expiry {
  h1('1 hour', 'Expires in ~1 day (server minimum)', Duration(hours: 1)),
  h24('24 hours', 'Expires in 1 day', Duration(hours: 24)),
  d7('7 days', 'Expires in 7 days', Duration(days: 7)),
  d30('30 days', 'Expires in 30 days', Duration(days: 30));

  const _Expiry(this.label, this.hint, this.duration);
  final String label;
  final String hint;
  final Duration duration;
}

class _CreateShareSheet extends ConsumerStatefulWidget {
  const _CreateShareSheet({
    required this.kind,
    required this.resourceId,
    this.label,
  });

  final String kind;
  final String resourceId;
  final String? label;

  @override
  ConsumerState<_CreateShareSheet> createState() => _CreateShareSheetState();
}

class _CreateShareSheetState extends ConsumerState<_CreateShareSheet> {
  _Expiry _expiry = _Expiry.d7;
  final _viewsController = TextEditingController();
  bool _creating = false;
  CreatedShare? _created;

  @override
  void dispose() {
    _viewsController.dispose();
    super.dispose();
  }

  Future<void> _create() async {
    final maxViews = int.tryParse(_viewsController.text.trim());
    setState(() => _creating = true);
    try {
      final created = await ref.read(shareRepoProvider).create(
            kind: widget.kind,
            resourceId: widget.resourceId,
            expirySeconds: _expiry.duration.inSeconds,
            maxViews: (maxViews != null && maxViews > 0) ? maxViews : null,
            label: widget.label,
          );
      if (!mounted) return;
      setState(() {
        _created = created;
        _creating = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _creating = false);
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
    }
  }

  Future<void> _share() async {
    final url = _created?.url;
    if (url == null || url.isEmpty) return;
    try {
      await SharePlus.instance.share(ShareParams(
        text: url,
        subject: widget.label ?? 'Nurby ${widget.kind}',
      ));
    } catch (_) {
      // Some platforms/contexts have no share sheet; fall back to clipboard.
      await _copy();
    }
  }

  Future<void> _copy() async {
    final url = _created?.url;
    if (url == null || url.isEmpty) return;
    await Clipboard.setData(ClipboardData(text: url));
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(const SnackBar(content: Text('Link copied')));
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, 18, 20, 24),
        child: _created == null ? _configStep() : _resultStep(_created!),
      ),
    );
  }

  Widget _configStep() {
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('Share ${widget.kind}',
            style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
        const SizedBox(height: 4),
        const Text(
          'Anyone with the link can view this item until it expires.',
          style: TextStyle(fontSize: 12.5, color: NurbyColors.mutedForeground),
        ),
        const SizedBox(height: 16),
        const Text('EXPIRES',
            style: TextStyle(
              fontFamily: 'Menlo',
              fontSize: 10,
              letterSpacing: 1.4,
              color: NurbyColors.accent,
              fontWeight: FontWeight.w600,
            )),
        const SizedBox(height: 8),
        Wrap(
          spacing: 8,
          children: [
            for (final e in _Expiry.values)
              ChoiceChip(
                label: Text(e.label),
                selected: _expiry == e,
                showCheckmark: false,
                selectedColor: NurbyColors.accent.withValues(alpha: 0.15),
                labelStyle: TextStyle(
                  fontSize: 13,
                  color: _expiry == e
                      ? NurbyColors.accent
                      : NurbyColors.foreground,
                ),
                side: BorderSide(
                    color:
                        _expiry == e ? NurbyColors.accent : NurbyColors.border),
                onSelected: (_) => setState(() => _expiry = e),
              ),
          ],
        ),
        const SizedBox(height: 4),
        Text(_expiry.hint,
            style: const TextStyle(
                fontSize: 11.5, color: NurbyColors.mutedForeground)),
        const SizedBox(height: 16),
        TextField(
          controller: _viewsController,
          keyboardType: TextInputType.number,
          inputFormatters: [FilteringTextInputFormatter.digitsOnly],
          decoration: const InputDecoration(
            labelText: 'View limit (optional)',
            hintText: 'Unlimited',
          ),
        ),
        const SizedBox(height: 18),
        SizedBox(
          width: double.infinity,
          child: FilledButton.icon(
            onPressed: _creating ? null : _create,
            icon: _creating
                ? const SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(
                        strokeWidth: 2, color: Colors.black),
                  )
                : const Icon(Icons.link, size: 18),
            label: Text(_creating ? 'Creating…' : 'Create link'),
          ),
        ),
      ],
    );
  }

  Widget _resultStep(CreatedShare created) {
    final expires = created.expiresAt != null
        ? DateFormat('MMM d, yyyy HH:mm').format(created.expiresAt!)
        : 'never';
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Row(
          children: [
            Icon(Icons.check_circle, color: NurbyColors.accent, size: 20),
            SizedBox(width: 8),
            Text('Link created',
                style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
          ],
        ),
        const SizedBox(height: 14),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: NurbyColors.cardElevated,
            border: Border.all(color: NurbyColors.border),
            borderRadius: BorderRadius.circular(10),
          ),
          child: Text(created.url,
              style: monoStyle.copyWith(color: NurbyColors.foreground)),
        ),
        const SizedBox(height: 10),
        Text(
          'Expires $expires'
          '${created.maxViews != null ? ' · max ${created.maxViews} views' : ''}',
          style: const TextStyle(
              fontSize: 12, color: NurbyColors.mutedForeground),
        ),
        const SizedBox(height: 16),
        Row(
          children: [
            Expanded(
              child: FilledButton.icon(
                onPressed: _share,
                icon: const Icon(Icons.ios_share, size: 18),
                label: const Text('Share'),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: OutlinedButton.icon(
                onPressed: _copy,
                style: OutlinedButton.styleFrom(
                  foregroundColor: NurbyColors.foreground,
                  side: const BorderSide(color: NurbyColors.border),
                  padding: const EdgeInsets.symmetric(vertical: 14),
                ),
                icon: const Icon(Icons.copy, size: 18),
                label: const Text('Copy'),
              ),
            ),
          ],
        ),
      ],
    );
  }
}
