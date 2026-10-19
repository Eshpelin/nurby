import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/i18n.dart';
import '../../core/providers.dart';
import '../../core/push.dart';
import '../../core/theme.dart';

/// Bottom-nav shell: Cameras, Timeline, Ask, Alerts, More.
class ShellScreen extends ConsumerStatefulWidget {
  const ShellScreen({super.key, required this.shell});

  final StatefulNavigationShell shell;

  @override
  ConsumerState<ShellScreen> createState() => _ShellScreenState();
}

/// Slim amber strip pinned above the shell content while the device has no
/// network path. Data on screen keeps rendering from provider caches.
class OfflineBanner extends StatelessWidget {
  const OfflineBanner({super.key});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      color: NurbyColors.warning,
      padding: EdgeInsets.only(
        top: MediaQuery.paddingOf(context).top + 4,
        bottom: 5,
        left: 12,
        right: 12,
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.cloud_off, size: 14, color: Colors.black),
          const SizedBox(width: 6),
          Text(
            t(context, 'common.offline_banner'),
            style: const TextStyle(
              color: Colors.black,
              fontSize: 12.5,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}

class _ShellScreenState extends ConsumerState<ShellScreen> {
  StatefulNavigationShell get shell => widget.shell;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance
        .addPostFrameCallback((_) => _maybePromptForNotifications());
  }

  /// One-time, right after first login: explain, then trigger the OS
  /// permission dialog (iOS alert/badge/sound, Android 13 POST_NOTIFICATIONS).
  Future<void> _maybePromptForNotifications() async {
    final prefs = ref.read(sharedPrefsProvider);
    if (prefs.getBool(kPermissionPromptedKey) ?? false) return;
    await prefs.setBool(kPermissionPromptedKey, true);
    if (!mounted) return;
    final enable = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(t(context, 'shell.enable_notifications_title')),
        content: Text(t(context, 'shell.enable_notifications_body')),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: Text(t(context, 'shell.not_now')),
          ),
          TextButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: Text(t(context, 'shell.enable')),
          ),
        ],
      ),
    );
    if (enable == true) {
      await ref.read(notificationServiceProvider).requestPermissions();
    }
  }

  @override
  Widget build(BuildContext context) {
    final unreviewed = ref.watch(unreviewedCountProvider).value ?? 0;
    final offline = ref.watch(isOfflineProvider);
    return Scaffold(
      body: Column(
        children: [
          if (offline) const OfflineBanner(),
          // The banner swallows the status-bar inset while it is showing, so
          // strip it from the tabs to avoid double top padding.
          Expanded(
            child: MediaQuery.removePadding(
              context: context,
              removeTop: offline,
              child: shell,
            ),
          ),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: shell.currentIndex,
        onDestinationSelected: (i) => shell.goBranch(
          i,
          initialLocation: i == shell.currentIndex,
        ),
        height: 64,
        labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
        // The five places, in the order of the questions they answer.
        // The unread-alert badge sits on Home, since that is where
        // "is everything all right" is answered.
        destinations: [
          NavigationDestination(
            icon: Badge(
              isLabelVisible: unreviewed > 0,
              backgroundColor: NurbyColors.danger,
              label: Text('$unreviewed'),
              child: const Icon(Icons.home_outlined),
            ),
            selectedIcon: Badge(
              isLabelVisible: unreviewed > 0,
              backgroundColor: NurbyColors.danger,
              label: Text('$unreviewed'),
              child: const Icon(Icons.home),
            ),
            label: t(context, 'nav.home'),
          ),
          NavigationDestination(
            icon: const Icon(Icons.videocam_outlined),
            selectedIcon: const Icon(Icons.videocam),
            label: t(context, 'nav.cameras'),
          ),
          NavigationDestination(
            icon: const Icon(Icons.view_timeline_outlined),
            selectedIcon: const Icon(Icons.view_timeline),
            label: t(context, 'nav.activity'),
          ),
          NavigationDestination(
            icon: const Icon(Icons.auto_awesome_outlined),
            selectedIcon: const Icon(Icons.auto_awesome),
            label: t(context, 'nav.ask'),
          ),
          NavigationDestination(
            icon: const Icon(Icons.people_outline),
            selectedIcon: const Icon(Icons.people),
            label: t(context, 'nav.people'),
          ),
        ],
      ),
    );
  }
}
