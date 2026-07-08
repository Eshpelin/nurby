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
    return Scaffold(
      body: shell,
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
