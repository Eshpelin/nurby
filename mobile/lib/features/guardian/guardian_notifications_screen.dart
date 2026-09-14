import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';

/// Guardian notifications: what a guardian has been told, and when.
///
/// Separate from the household notification list because they answer to
/// different people. A guardian sees only what their links allow, and
/// the household never sees this list at all.
final guardianNotificationsProvider =
    FutureProvider<List<Map<String, dynamic>>>(
        (ref) => ref.watch(guardianRepoProvider).notifications());

class GuardianNotificationsScreen extends ConsumerWidget {
  const GuardianNotificationsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(guardianNotificationsProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Updates')),
      body: async.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => ListView(children: [
          const SizedBox(height: 96),
          Center(
              child: Text(apiErrorMessage(e),
                  textAlign: TextAlign.center,
                  style: const TextStyle(color: NurbyColors.mutedForeground))),
          const SizedBox(height: 12),
          Center(
            child: OutlinedButton(
              onPressed: () => ref.invalidate(guardianNotificationsProvider),
              child: const Text('Retry'),
            ),
          ),
        ]),
        data: (items) => items.isEmpty
            ? ListView(children: const [
                SizedBox(height: 96),
                Icon(Icons.notifications_none,
                    size: 40, color: NurbyColors.mutedForeground),
                SizedBox(height: 12),
                Center(
                    child: Text('Nothing yet',
                        style: TextStyle(fontWeight: FontWeight.w600))),
                SizedBox(height: 6),
                Padding(
                  padding: EdgeInsets.symmetric(horizontal: 40),
                  child: Text(
                    'Alerts you have chosen to receive will appear here.',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                        fontSize: 12, color: NurbyColors.mutedForeground),
                  ),
                ),
              ])
            : RefreshIndicator(
                onRefresh: () async =>
                    ref.invalidate(guardianNotificationsProvider),
                child: ListView.builder(
                  itemCount: items.length,
                  itemBuilder: (_, i) {
                    final n = items[i];
                    final unread = n['read'] != true;
                    return ListTile(
                      // Unread is marked with weight rather than a badge:
                      // this list is read top to bottom, and a column of
                      // dots is noise.
                      title: Text('${n['message']}',
                          style: TextStyle(
                              fontSize: 13,
                              fontWeight:
                                  unread ? FontWeight.w600 : FontWeight.w400)),
                      subtitle: n['created_at'] == null
                          ? null
                          : Text(
                              DateFormat('MMM d, HH:mm').format(
                                  DateTime.parse('${n['created_at']}')
                                      .toLocal()),
                              style: const TextStyle(
                                  color: NurbyColors.mutedForeground,
                                  fontSize: 11)),
                      onTap: unread
                          ? () async {
                              await ref
                                  .read(guardianRepoProvider)
                                  .markNotificationRead(n['id'] as String);
                              ref.invalidate(guardianNotificationsProvider);
                            }
                          : null,
                    );
                  },
                ),
              ),
      ),
    );
  }
}
