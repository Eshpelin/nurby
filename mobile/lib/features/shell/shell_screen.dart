import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

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
      child: const Row(
        mainAxisAlignment: MainAxisAlignment.center,
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.cloud_off, size: 14, color: Colors.black),
          SizedBox(width: 6),
          Text(
            'Offline — showing cached data',
            style: TextStyle(
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
        title: const Text('Enable notifications?'),
        content: const Text(
            'Nurby can alert you when rules fire, even while the app is in '
            'the background.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Not now'),
          ),
          TextButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('Enable'),
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
        destinations: [
          const NavigationDestination(
            icon: Icon(Icons.videocam_outlined),
            selectedIcon: Icon(Icons.videocam),
            label: 'Cameras',
          ),
          const NavigationDestination(
            icon: Icon(Icons.view_timeline_outlined),
            selectedIcon: Icon(Icons.view_timeline),
            label: 'Timeline',
          ),
          const NavigationDestination(
            icon: Icon(Icons.auto_awesome_outlined),
            selectedIcon: Icon(Icons.auto_awesome),
            label: 'Ask',
          ),
          NavigationDestination(
            icon: Badge(
              isLabelVisible: unreviewed > 0,
              backgroundColor: NurbyColors.danger,
              label: Text('$unreviewed'),
              child: const Icon(Icons.notifications_outlined),
            ),
            selectedIcon: Badge(
              isLabelVisible: unreviewed > 0,
              backgroundColor: NurbyColors.danger,
              label: Text('$unreviewed'),
              child: const Icon(Icons.notifications),
            ),
            label: 'Alerts',
          ),
          const NavigationDestination(
            icon: Icon(Icons.menu),
            label: 'More',
          ),
        ],
      ),
    );
  }
}
