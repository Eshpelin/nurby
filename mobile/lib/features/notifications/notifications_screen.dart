import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../models/models.dart';

/// Notification list; family key is the unread-only toggle.
final _notificationsProvider =
    FutureProvider.family<List<AppNotification>, bool>((ref, unreadOnly) =>
        ref.watch(notificationRepoProvider).list(unreadOnly: unreadOnly));

String _relativeTime(DateTime t) {
  final diff = DateTime.now().difference(t);
  if (diff.inSeconds < 60) return 'just now';
  if (diff.inMinutes < 60) return '${diff.inMinutes}m ago';
  if (diff.inHours < 24) return '${diff.inHours}h ago';
  if (diff.inDays < 7) return '${diff.inDays}d ago';
  return DateFormat('MMM d').format(t);
}

/// Notifications tab: read/unread inbox.
class NotificationsScreen extends ConsumerStatefulWidget {
  const NotificationsScreen({super.key});

  @override
  ConsumerState<NotificationsScreen> createState() =>
      _NotificationsScreenState();
}

class _NotificationsScreenState extends ConsumerState<NotificationsScreen> {
  bool _unreadOnly = false;

  void _invalidate() {
    ref.invalidate(_notificationsProvider);
    ref.invalidate(unreadNotificationsProvider);
  }

  Future<void> _markRead(AppNotification n) async {
    try {
      await ref.read(notificationRepoProvider).markRead(n.id);
      if (mounted) _invalidate();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    }
  }

  Future<void> _markAllRead() async {
    try {
      await ref.read(notificationRepoProvider).markAllRead();
      if (mounted) _invalidate();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    ref.listen(wsMessagesProvider, (_, next) {
      if (next.value?['type'] == 'notification') {
        ref.invalidate(_notificationsProvider);
      }
    });

    final notifications = ref.watch(_notificationsProvider(_unreadOnly));

    return Scaffold(
      appBar: AppBar(
        title: const Text('Notifications'),
        actions: [
          TextButton(
            onPressed: _markAllRead,
            child: const Text(
              'Mark all read',
              style: TextStyle(
                  color: NurbyColors.accent, fontWeight: FontWeight.w600),
            ),
          ),
        ],
      ),
      body: Column(
        children: [
          SizedBox(
            height: 52,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              children: [
                _chip('All', !_unreadOnly,
                    () => setState(() => _unreadOnly = false)),
                _chip('Unread only', _unreadOnly,
                    () => setState(() => _unreadOnly = true)),
              ],
            ),
          ),
          Expanded(
            child: notifications.when(
              loading: () => const Center(child: CircularProgressIndicator()),
              error: (e, _) => Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(apiErrorMessage(e),
                        style: const TextStyle(
                            color: NurbyColors.mutedForeground)),
                    const SizedBox(height: 12),
                    TextButton(
                      onPressed: () =>
                          ref.invalidate(_notificationsProvider(_unreadOnly)),
                      child: const Text('Retry'),
                    ),
                  ],
                ),
              ),
              data: (items) => RefreshIndicator(
                onRefresh: () async {
                  _invalidate();
                  await ref.read(_notificationsProvider(_unreadOnly).future);
                },
                child: items.isEmpty
                    ? ListView(
                        physics: const AlwaysScrollableScrollPhysics(),
                        children: [
                          Padding(
                            padding: const EdgeInsets.only(top: 96),
                            child: Center(
                              child: Text(
                                _unreadOnly
                                    ? 'No unread notifications'
                                    : 'No notifications yet',
                                style: const TextStyle(
                                    color: NurbyColors.mutedForeground),
                              ),
                            ),
                          ),
                        ],
                      )
                    : ListView.separated(
                        physics: const AlwaysScrollableScrollPhysics(),
                        padding: const EdgeInsets.fromLTRB(12, 4, 12, 24),
                        itemCount: items.length,
                        separatorBuilder: (_, __) => const SizedBox(height: 8),
                        itemBuilder: (context, i) => _row(items[i]),
                      ),
              ),
            ),
          ),
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

  Widget _row(AppNotification n) {
    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: n.read ? null : () => _markRead(n),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Padding(
                padding: const EdgeInsets.only(top: 5),
                child: Container(
                  width: 8,
                  height: 8,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color:
                        n.read ? Colors.transparent : NurbyColors.accent,
                  ),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      n.title.isEmpty ? 'Notification' : n.title,
                      style: TextStyle(
                        fontSize: 14,
                        fontWeight:
                            n.read ? FontWeight.w400 : FontWeight.w600,
                      ),
                    ),
                    if (n.body.isNotEmpty) ...[
                      const SizedBox(height: 3),
                      Text(
                        n.body,
                        maxLines: 3,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                            fontSize: 13,
                            color: NurbyColors.mutedForeground,
                            height: 1.35),
                      ),
                    ],
                    const SizedBox(height: 6),
                    Text(_relativeTime(n.createdAt), style: monoStyle),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
