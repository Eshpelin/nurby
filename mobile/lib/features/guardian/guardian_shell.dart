import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/providers.dart';
import '../../core/theme.dart';
import 'guardian_notifications_screen.dart';
import 'guardian_screen.dart';

/// Guardian mode (docs/ia-rollout.md, phase 5).
///
/// A guardian is not a household member. They signed in to watch one
/// person, and the five places, Cameras, Activity, Ask, People, are not
/// theirs to see. The API already refuses them; this is the shell that
/// stops the app offering them. Two places: Home (their dependants) and
/// Updates (what they have been told). Sign out lives on Home.
class GuardianShell extends ConsumerStatefulWidget {
  const GuardianShell({super.key, this.initialTab = 0});

  final int initialTab;

  @override
  ConsumerState<GuardianShell> createState() => _GuardianShellState();
}

class _GuardianShellState extends ConsumerState<GuardianShell> {
  late int _tab = widget.initialTab;

  @override
  Widget build(BuildContext context) {
    final offline = ref.watch(isOfflineProvider);
    return Scaffold(
      body: Column(
        children: [
          if (offline) const _OfflineStrip(),
          Expanded(
            child: IndexedStack(
              index: _tab,
              children: const [
                GuardianScreen(),
                GuardianNotificationsScreen(),
              ],
            ),
          ),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (i) => setState(() => _tab = i),
        height: 64,
        labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.home_outlined),
            selectedIcon: Icon(Icons.home),
            label: 'Home',
          ),
          NavigationDestination(
            icon: Icon(Icons.notifications_none),
            selectedIcon: Icon(Icons.notifications),
            label: 'Updates',
          ),
        ],
      ),
    );
  }
}

class _OfflineStrip extends StatelessWidget {
  const _OfflineStrip();
  @override
  Widget build(BuildContext context) => Container(
        width: double.infinity,
        color: NurbyColors.warning.withValues(alpha: 0.15),
        padding: const EdgeInsets.fromLTRB(12, 40, 12, 8),
        child: const Text('Offline. Showing what was last loaded.',
            style: TextStyle(fontSize: 12, color: NurbyColors.warning)),
      );
}
