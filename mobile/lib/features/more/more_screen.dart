import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/push.dart';
import '../../core/theme.dart';
import '../../core/ws_client.dart';
import '../events/events_screen.dart';
import '../notifications/notifications_screen.dart';
import '../rules/rules_screen.dart';
import '../timeline/timeline_screen.dart';

/// Hub for secondary destinations (mirrors the web navbar's long tail).
class MoreScreen extends ConsumerWidget {
  const MoreScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authProvider);
    final wsStatus = ref.watch(wsStatusProvider).value;
    final user = auth.user;
    final isGuardian = user?.role == 'guardian';

    final items = <_NavItem>[
      if (!isGuardian) ...[
        _NavItem('Rules', Icons.rule_outlined, '/more/rules'),
        _NavItem('People', Icons.people_outline, '/more/people'),
        _NavItem('Vehicles', Icons.directions_car_outlined, '/more/vehicles'),
        _NavItem('Recordings', Icons.video_library_outlined, '/more/recordings'),
        _NavItem('Search', Icons.search, '/more/search'),
        _NavItem('Share links', Icons.link, '/more/shares'),
        _NavItem(
            'Notifications', Icons.notifications_none, '/more/notifications'),
      ],
      _NavItem('Guardian', Icons.shield_outlined, '/more/guardian'),
      if (!isGuardian)
        _NavItem('Settings', Icons.settings_outlined, '/more/settings'),
    ];

    return Scaffold(
      appBar: AppBar(title: const Text('More')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Card(
            child: ListTile(
              leading: CircleAvatar(
                backgroundColor: NurbyColors.accent.withValues(alpha: 0.15),
                child: Text(
                  (user?.displayName.isNotEmpty ?? false)
                      ? user!.displayName[0].toUpperCase()
                      : '?',
                  style: const TextStyle(
                      color: NurbyColors.accent, fontWeight: FontWeight.w700),
                ),
              ),
              title: Text(user?.displayName ?? ''),
              subtitle: Text(user?.email ?? '',
                  style: const TextStyle(color: NurbyColors.mutedForeground)),
              trailing: _ConnectionDot(status: wsStatus),
            ),
          ),
          const SizedBox(height: 16),
          ...items.map((item) => ListTile(
                leading: Icon(item.icon, color: NurbyColors.mutedForeground),
                title: Text(item.label),
                trailing: const Icon(Icons.chevron_right,
                    size: 20, color: NurbyColors.mutedForeground),
                onTap: () => context.go(item.path),
              )),
          const Divider(height: 32),
          ListTile(
            leading:
                const Icon(Icons.sync, color: NurbyColors.mutedForeground),
            title: const Text('Sync now'),
            subtitle: const Text('Refresh cameras, timeline and alerts',
                style: TextStyle(
                    fontSize: 12, color: NurbyColors.mutedForeground)),
            onTap: () => _syncNow(context, ref),
          ),
          ListTile(
            leading: const Icon(Icons.notifications_active_outlined,
                color: NurbyColors.mutedForeground),
            title: const Text('Check alerts now'),
            subtitle: const Text('Poll the server for new alerts',
                style: TextStyle(
                    fontSize: 12, color: NurbyColors.mutedForeground)),
            onTap: () => _checkAlertsNow(context, ref),
          ),
          const Divider(height: 32),
          ListTile(
            leading: const Icon(Icons.logout, color: NurbyColors.danger),
            title:
                const Text('Sign out', style: TextStyle(color: NurbyColors.danger)),
            onTap: () => ref.read(authProvider.notifier).logout(),
          ),
        ],
      ),
    );
  }

  /// Refresh at will: drop every cached list so screens refetch on next look.
  void _syncNow(BuildContext context, WidgetRef ref) {
    ref.invalidate(camerasProvider);
    ref.invalidate(unreadNotificationsProvider);
    ref.invalidate(unreviewedCountProvider);
    ref.invalidate(eventsProvider);
    ref.invalidate(timelineProvider);
    ref.invalidate(notificationsListProvider);
    ref.invalidate(rulesProvider);
    ScaffoldMessenger.of(context)
        .showSnackBar(const SnackBar(content: Text('Synced')));
  }

  Future<void> _checkAlertsNow(BuildContext context, WidgetRef ref) async {
    final messenger = ScaffoldMessenger.of(context);
    try {
      final result = await checkAlertsNow(
        ref.read(apiClientProvider),
        ref.read(sharedPrefsProvider),
        ref.read(notificationServiceProvider),
      );
      messenger.showSnackBar(SnackBar(
        content: Text(result.newAlerts > 0
            ? (result.newAlerts == 1
                ? '1 new alert'
                : '${result.newAlerts} new alerts')
            : 'No new alerts'),
      ));
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
    }
  }
}

class _NavItem {
  const _NavItem(this.label, this.icon, this.path);
  final String label;
  final IconData icon;
  final String path;
}

class _ConnectionDot extends StatelessWidget {
  const _ConnectionDot({this.status});
  final WsStatus? status;

  @override
  Widget build(BuildContext context) {
    final color = switch (status) {
      WsStatus.connected => NurbyColors.accent,
      WsStatus.connecting || WsStatus.reconnecting => NurbyColors.warning,
      _ => NurbyColors.danger,
    };
    return Container(
      width: 10,
      height: 10,
      decoration: BoxDecoration(color: color, shape: BoxShape.circle),
    );
  }
}
