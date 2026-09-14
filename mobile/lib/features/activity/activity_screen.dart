import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme.dart';
import '../conversations/conversations_screen.dart';
import '../digests/digests_screen.dart';
import '../events/events_screen.dart';
import '../incidents/incidents_screen.dart';
import '../journeys/journeys_screen.dart';
import '../recordings/recordings_screen.dart';
import '../timeline/timeline_screen.dart';

/// Activity: what happened.
///
/// One place for the seven kinds of thing the household used to reach
/// through seven More-menu entries. The kind is a filter chip, and each
/// chip shows the existing list for that kind, embedded. The lists are
/// unchanged; only where they live has.
///
/// The order of the chips is the order of the question. "All" and
/// "Alerts" are what most people want most of the time; the rest are
/// for when you already know what you are looking for.
enum ActivityKind {
  all('All', Icons.view_timeline_outlined),
  alerts('Alerts', Icons.notifications_none),
  sightings('Sightings', Icons.visibility_outlined),
  incidents('Incidents', Icons.inbox_outlined),
  journeys('Journeys', Icons.route_outlined),
  conversations('Conversations', Icons.forum_outlined),
  recordings('Recordings', Icons.video_library_outlined),
  recaps('Camera recaps', Icons.article_outlined);

  const ActivityKind(this.label, this.icon);
  final String label;
  final IconData icon;

  /// The chip name as it appears in the URL, so `/activity?kind=alerts`
  /// deep-links to a filter and old routes can redirect into one.
  String get slug => name;

  static ActivityKind fromSlug(String? s) =>
      ActivityKind.values.firstWhere((k) => k.slug == s, orElse: () => ActivityKind.all);
}

class ActivityScreen extends StatefulWidget {
  const ActivityScreen({super.key, this.initialKind = ActivityKind.all});

  final ActivityKind initialKind;

  @override
  State<ActivityScreen> createState() => _ActivityScreenState();
}

class _ActivityScreenState extends State<ActivityScreen> {
  late ActivityKind _kind = widget.initialKind;

  @override
  void didUpdateWidget(ActivityScreen old) {
    super.didUpdateWidget(old);
    // A redirect from an old route lands with a different initial kind
    // while this screen is already mounted.
    if (old.initialKind != widget.initialKind) _kind = widget.initialKind;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Activity'),
        actions: [
          IconButton(
            tooltip: 'Search',
            icon: const Icon(Icons.search),
            onPressed: () => context.push('/search'),
          ),
        ],
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(46),
          child: SizedBox(
            height: 46,
            child: ListView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.fromLTRB(12, 4, 12, 8),
              children: [
                for (final k in ActivityKind.values)
                  Padding(
                    padding: const EdgeInsets.only(right: 6),
                    child: ChoiceChip(
                      avatar: Icon(k.icon, size: 14,
                          color: _kind == k ? Colors.black : NurbyColors.mutedForeground),
                      label: Text(k.label, style: const TextStyle(fontSize: 12)),
                      selected: _kind == k,
                      selectedColor: NurbyColors.accent,
                      labelStyle: TextStyle(color: _kind == k ? Colors.black : null),
                      onSelected: (_) => setState(() => _kind = k),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
      // Each kind keeps its own scroll position and loaded pages, so
      // flicking between chips does not refetch what was just read.
      body: IndexedStack(
        index: _kind.index,
        children: const [
          TimelineScreen(embedded: true),
          EventsScreen(embedded: true),
          TimelineScreen(embedded: true, sightingsOnly: true),
          IncidentsScreen(embedded: true),
          JourneysScreen(embedded: true),
          ConversationsScreen(embedded: true),
          RecordingsScreen(embedded: true),
          DigestsScreen(embedded: true),
        ],
      ),
    );
  }
}
