import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../models/models.dart';

/// My share links (admins see everyone's, mirroring the API).
final mySharesProvider = FutureProvider<List<ShareLink>>(
    (ref) => ref.watch(shareRepoProvider).listMine());

/// Manage share links: what is shared, when it dies, how often it was viewed.
class SharesScreen extends ConsumerWidget {
  const SharesScreen({super.key});

  Future<void> _revoke(BuildContext context, WidgetRef ref, ShareLink s) async {
    final messenger = ScaffoldMessenger.of(context);
    try {
      await ref.read(shareRepoProvider).revoke(s.id);
      ref.invalidate(mySharesProvider);
      messenger.showSnackBar(const SnackBar(content: Text('Link revoked')));
    } catch (e) {
      ref.invalidate(mySharesProvider); // restore swiped-away row
      messenger.showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final shares = ref.watch(mySharesProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Share links')),
      body: shares.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(apiErrorMessage(e),
                  style: const TextStyle(color: NurbyColors.mutedForeground)),
              const SizedBox(height: 12),
              TextButton(
                onPressed: () => ref.invalidate(mySharesProvider),
                child: const Text('Retry'),
              ),
            ],
          ),
        ),
        data: (items) => RefreshIndicator(
          onRefresh: () async {
            ref.invalidate(mySharesProvider);
            await ref.read(mySharesProvider.future);
          },
          child: items.isEmpty
              ? ListView(
                  physics: const AlwaysScrollableScrollPhysics(),
                  children: const [
                    SizedBox(height: 120),
                    Icon(Icons.link_off,
                        size: 44, color: NurbyColors.mutedForeground),
                    SizedBox(height: 14),
                    Center(
                      child: Text('No share links',
                          style: TextStyle(
                              fontSize: 16, fontWeight: FontWeight.w600)),
                    ),
                    SizedBox(height: 6),
                    Center(
                      child: Text(
                        'Share a recording or alert to create one.',
                        style: TextStyle(
                            color: NurbyColors.mutedForeground, fontSize: 13),
                      ),
                    ),
                  ],
                )
              : ListView.separated(
                  physics: const AlwaysScrollableScrollPhysics(),
                  padding: const EdgeInsets.fromLTRB(12, 8, 12, 24),
                  itemCount: items.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 8),
                  itemBuilder: (context, i) =>
                      _ShareRow(share: items[i], onRevoke: _revoke),
                ),
        ),
      ),
    );
  }
}

class _ShareRow extends ConsumerWidget {
  const _ShareRow({required this.share, required this.onRevoke});

  final ShareLink share;
  final Future<void> Function(BuildContext, WidgetRef, ShareLink) onRevoke;

  bool get _active => share.status == 'active';

  IconData get _kindIcon => switch (share.kind) {
        'recording' => Icons.video_library_outlined,
        'observation' => Icons.image_outlined,
        'event' => Icons.notifications_outlined,
        _ => Icons.link,
      };

  Color get _statusColor => switch (share.status) {
        'active' => NurbyColors.accent,
        'expired' || 'exhausted' => NurbyColors.warning,
        _ => NurbyColors.mutedForeground, // revoked
      };

  String get _expiryText {
    final at = share.expiresAt;
    if (at == null) return 'no expiry';
    if (!_active) return DateFormat('MMM d, HH:mm').format(at);
    final left = at.difference(DateTime.now());
    if (left.isNegative) return 'expired';
    if (left.inHours < 1) return 'expires in ${left.inMinutes}m';
    if (left.inHours < 48) return 'expires in ${left.inHours}h';
    return 'expires in ${left.inDays}d';
  }

  String get _viewsText => share.maxViews == null
      ? '${share.viewCount} views'
      : '${share.viewCount}/${share.maxViews} views';

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final card = Card(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        child: Row(
          children: [
            Container(
              width: 42,
              height: 42,
              decoration: BoxDecoration(
                color: NurbyColors.cardElevated,
                border: Border.all(color: NurbyColors.border),
                borderRadius: BorderRadius.circular(10),
              ),
              child: Icon(_kindIcon,
                  size: 20,
                  color: _active
                      ? NurbyColors.accent
                      : NurbyColors.mutedForeground),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Text(
                        share.label ?? share.kind,
                        style: const TextStyle(
                            fontWeight: FontWeight.w600, fontSize: 14),
                        overflow: TextOverflow.ellipsis,
                      ),
                      const SizedBox(width: 8),
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 7, vertical: 1.5),
                        decoration: BoxDecoration(
                          color: _statusColor.withValues(alpha: 0.12),
                          borderRadius: BorderRadius.circular(20),
                        ),
                        child: Text(
                          share.status,
                          style: TextStyle(fontSize: 10.5, color: _statusColor),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 3),
                  Text('$_expiryText · $_viewsText', style: monoStyle),
                ],
              ),
            ),
            if (share.status != 'revoked')
              IconButton(
                tooltip: 'Revoke',
                icon: const Icon(Icons.link_off,
                    size: 20, color: NurbyColors.danger),
                onPressed: () => onRevoke(context, ref, share),
              ),
          ],
        ),
      ),
    );

    if (share.status == 'revoked') return card;

    return Dismissible(
      key: ValueKey(share.id),
      direction: DismissDirection.endToStart,
      background: Container(
        alignment: Alignment.centerRight,
        padding: const EdgeInsets.only(right: 20),
        decoration: BoxDecoration(
          color: NurbyColors.danger.withValues(alpha: 0.2),
          borderRadius: BorderRadius.circular(12),
        ),
        child: const Icon(Icons.link_off, color: NurbyColors.danger),
      ),
      onDismissed: (_) => onRevoke(context, ref, share),
      child: card,
    );
  }
}
