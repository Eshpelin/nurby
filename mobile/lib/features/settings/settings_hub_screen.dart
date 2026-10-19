import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/i18n.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';

/// Settings hub: the gear behind Home.
///
/// What used to be a fifteen-entry More menu, sorted by what a person
/// is trying to do rather than by what the backend calls it. Every
/// destination the old menu had is still here; the sections are the
/// change.
class SettingsHubScreen extends ConsumerWidget {
  const SettingsHubScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final user = ref.watch(authProvider).user;
    final isAdmin = user?.isAdmin ?? false;

    final sections = <(String, List<_Item>)>[
      (
        t(context, 'settings_hub.section_alerts'),
        [
          _Item(t(context, 'settings_hub.review_center'), t(context, 'settings_hub.review_center_hint'), Icons.fact_check_outlined, '/settings/review'),
          _Item(t(context, 'settings_hub.alert_rules'), t(context, 'settings_hub.alert_rules_hint'), Icons.rule_outlined, '/settings/rules'),
          _Item(t(context, 'settings_hub.notifications'), t(context, 'settings_hub.notifications_hint'), Icons.notifications_none, '/settings/notifications'),
          _Item(t(context, 'settings_hub.scheduled_questions'), t(context, 'settings_hub.scheduled_questions_hint'), Icons.schedule_send_outlined, '/settings/reports'),
        ],
      ),
      (
        t(context, 'settings_hub.section_sharing'),
        [
          _Item(t(context, 'settings_hub.guardians'), t(context, 'settings_hub.guardians_hint'), Icons.shield_outlined, '/settings/guardian/admin'),
          _Item(t(context, 'settings_hub.share_links'), t(context, 'settings_hub.share_links_hint'), Icons.link, '/settings/shares'),
        ],
      ),
      (
        t(context, 'settings_hub.section_household_ai'),
        [
          _Item(t(context, 'settings_hub.household_ai'), t(context, 'settings_hub.household_ai_hint'), Icons.home_outlined, '/settings/general'),
        ],
      ),
      if (isAdmin)
        (
          t(context, 'settings_hub.section_admin'),
          [
            _Item(t(context, 'settings_hub.who_sees_cameras'), t(context, 'settings_hub.who_sees_cameras_hint'), Icons.admin_panel_settings_outlined, '/settings/access'),
            _Item(t(context, 'settings_hub.ai_backlog'), t(context, 'settings_hub.ai_backlog_hint'), Icons.speed_outlined, '/settings/pipeline'),
            _Item(t(context, 'settings_hub.everyones_questions'), t(context, 'settings_hub.everyones_questions_hint'), Icons.question_answer_outlined, '/settings/ask-admin'),
          ],
        ),
    ];

    return Scaffold(
      appBar: AppBar(title: Text(t(context, 'settings.title'))),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 24),
        children: [
          Card(
            child: ListTile(
              leading: CircleAvatar(
                backgroundColor: NurbyColors.accent.withValues(alpha: 0.15),
                child: Text(
                  (user?.displayName.isNotEmpty ?? false) ? user!.displayName[0].toUpperCase() : '?',
                  style: const TextStyle(color: NurbyColors.accent, fontWeight: FontWeight.w700),
                ),
              ),
              title: Text(user?.displayName ?? ''),
              subtitle: Text(user?.email ?? '',
                  style: const TextStyle(color: NurbyColors.mutedForeground)),
            ),
          ),
          for (final (title, items) in sections) ...[
            Padding(
              padding: const EdgeInsets.fromLTRB(4, 18, 4, 6),
              child: Text(title.toUpperCase(),
                  style: const TextStyle(
                      fontFamily: 'Menlo', fontSize: 10, letterSpacing: 1.4,
                      color: NurbyColors.accent, fontWeight: FontWeight.w600)),
            ),
            Card(
              child: Column(children: [
                for (final it in items)
                  ListTile(
                    leading: Icon(it.icon, color: NurbyColors.mutedForeground),
                    title: Text(it.title),
                    subtitle: Text(it.hint,
                        style: const TextStyle(fontSize: 12, color: NurbyColors.mutedForeground)),
                    trailing: const Icon(Icons.chevron_right, size: 20, color: NurbyColors.mutedForeground),
                    onTap: () => context.push(it.path),
                  ),
              ]),
            ),
          ],
          const SizedBox(height: 18),
          Card(
            child: ListTile(
              leading: const Icon(Icons.logout, color: NurbyColors.mutedForeground),
              title: Text(t(context, 'settings_hub.sign_out')),
              onTap: () => ref.read(authProvider.notifier).logout(),
            ),
          ),
        ],
      ),
    );
  }
}

class _Item {
  const _Item(this.title, this.hint, this.icon, this.path);
  final String title;
  final String hint;
  final IconData icon;
  final String path;
}
