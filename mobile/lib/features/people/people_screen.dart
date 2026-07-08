import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../models/models.dart';

final _peopleProvider = FutureProvider<List<Person>>((ref) async {
  final repo = ref.watch(personRepoProvider);
  try {
    return await repo.activitySummary();
  } catch (_) {
    return repo.list();
  }
});

final _suggestionsProvider = FutureProvider<List<FaceClusterSuggestion>>(
    (ref) => ref.watch(personRepoProvider).suggestions());

final _personActivityProvider =
    FutureProvider.family<List<Map<String, dynamic>>, String>((ref, id) async {
  final j =
      await ref.watch(apiClientProvider).getJson('/api/persons/activity/$id');
  return (j as List? ?? [])
      .whereType<Map>()
      .map((m) => m.cast<String, dynamic>())
      .toList();
});

String _ago(DateTime? t) {
  if (t == null) return 'never';
  final d = DateTime.now().difference(t);
  if (d.inMinutes < 1) return 'just now';
  if (d.inMinutes < 60) return '${d.inMinutes}m ago';
  if (d.inHours < 24) return '${d.inHours}h ago';
  return '${d.inDays}d ago';
}

/// Known people + unknown face cluster suggestions.
class PeopleScreen extends ConsumerWidget {
  const PeopleScreen({super.key});

  Future<void> _refresh(WidgetRef ref) {
    ref.invalidate(_suggestionsProvider);
    return ref.refresh(_peopleProvider.future);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final peopleAsync = ref.watch(_peopleProvider);
    final suggestionsAsync = ref.watch(_suggestionsProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('People')),
      body: RefreshIndicator(
        onRefresh: () => _refresh(ref),
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(12),
          children: [
            _sectionLabel('PEOPLE'),
            peopleAsync.when(
              loading: () => const Padding(
                padding: EdgeInsets.all(24),
                child: Center(child: CircularProgressIndicator()),
              ),
              error: (e, _) => Padding(
                padding: const EdgeInsets.all(12),
                child: Text(apiErrorMessage(e),
                    style:
                        const TextStyle(color: NurbyColors.mutedForeground)),
              ),
              data: (people) => people.isEmpty
                  ? const Padding(
                      padding: EdgeInsets.all(12),
                      child: Text('No known people yet',
                          style:
                              TextStyle(color: NurbyColors.mutedForeground)),
                    )
                  : GridView.count(
                      crossAxisCount: 2,
                      shrinkWrap: true,
                      physics: const NeverScrollableScrollPhysics(),
                      mainAxisSpacing: 8,
                      crossAxisSpacing: 8,
                      childAspectRatio: 1.05,
                      children: [
                        for (final p in people) _PersonTile(person: p),
                      ],
                    ),
            ),
            _sectionLabel('UNKNOWN FACES'),
            suggestionsAsync.when(
              loading: () => const Padding(
                padding: EdgeInsets.all(24),
                child: Center(child: CircularProgressIndicator()),
              ),
              error: (e, _) => Padding(
                padding: const EdgeInsets.all(12),
                child: Text(apiErrorMessage(e),
                    style:
                        const TextStyle(color: NurbyColors.mutedForeground)),
              ),
              data: (suggestions) => suggestions.isEmpty
                  ? const Padding(
                      padding: EdgeInsets.all(12),
                      child: Text('No unknown faces waiting for a name',
                          style:
                              TextStyle(color: NurbyColors.mutedForeground)),
                    )
                  : SizedBox(
                      height: 230,
                      child: ListView.separated(
                        scrollDirection: Axis.horizontal,
                        itemCount: suggestions.length,
                        separatorBuilder: (_, __) => const SizedBox(width: 8),
                        itemBuilder: (context, i) =>
                            _ClusterCard(suggestion: suggestions[i]),
                      ),
                    ),
            ),
            const SizedBox(height: 24),
          ],
        ),
      ),
    );
  }

  Widget _sectionLabel(String text) {
    return Padding(
      padding: const EdgeInsets.only(top: 6, bottom: 8, left: 4),
      child: Text(
        text,
        style: const TextStyle(
          fontFamily: 'Menlo',
          fontSize: 10,
          letterSpacing: 1.4,
          color: NurbyColors.accent,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }
}

class _PersonTile extends ConsumerWidget {
  const _PersonTile({required this.person});
  final Person person;

  void _showActivity(BuildContext context, WidgetRef ref) {
    showModalBottomSheet<void>(
      context: context,
      backgroundColor: NurbyColors.cardElevated,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(16))),
      builder: (_) => _PersonActivitySheet(person: person),
    );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final api = ref.watch(apiClientProvider);
    final initial = person.displayName.isNotEmpty
        ? person.displayName[0].toUpperCase()
        : '?';

    return Card(
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: () => _showActivity(context, ref),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              CircleAvatar(
                radius: 28,
                backgroundColor: NurbyColors.accent.withValues(alpha: 0.15),
                foregroundImage: person.photoPath != null
                    ? NetworkImage(
                        api.mediaUrl('/api/persons/${person.id}/photo'))
                    : null,
                child: Text(initial,
                    style: const TextStyle(
                        color: NurbyColors.accent,
                        fontSize: 20,
                        fontWeight: FontWeight.w600)),
              ),
              const SizedBox(height: 8),
              Text(person.displayName,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                      fontWeight: FontWeight.w600, fontSize: 14)),
              if (person.relationship != null)
                Text(person.relationship!,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                        color: NurbyColors.mutedForeground, fontSize: 12)),
              const SizedBox(height: 4),
              Text(
                '24h: ${person.sightings24h ?? 0} sightings',
                style: monoStyle.copyWith(fontSize: 11),
              ),
              Text(
                'last seen ${_ago(person.lastSeenAt)}',
                style: monoStyle.copyWith(fontSize: 11),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _PersonActivitySheet extends ConsumerWidget {
  const _PersonActivitySheet({required this.person});
  final Person person;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final activityAsync = ref.watch(_personActivityProvider(person.id));
    final cameras = ref.watch(camerasProvider).value ?? [];

    String cameraName(String? id) {
      final match = cameras.where((c) => c.id == id).toList();
      return match.isNotEmpty ? match.first.name : 'Camera';
    }

    return SafeArea(
      child: SizedBox(
        height: MediaQuery.of(context).size.height * 0.6,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
              child: Text('${person.displayName} recent activity',
                  style: const TextStyle(
                      fontWeight: FontWeight.w600, fontSize: 16)),
            ),
            const Divider(height: 1),
            Expanded(
              child: activityAsync.when(
                loading: () =>
                    const Center(child: CircularProgressIndicator()),
                error: (e, _) => Center(
                  child: Text(apiErrorMessage(e),
                      style: const TextStyle(
                          color: NurbyColors.mutedForeground)),
                ),
                data: (items) => items.isEmpty
                    ? const Center(
                        child: Text('No recent activity',
                            style: TextStyle(
                                color: NurbyColors.mutedForeground)),
                      )
                    : ListView.builder(
                        itemCount: items.length,
                        itemBuilder: (context, i) {
                          final item = items[i];
                          final startedAt = DateTime.tryParse(
                                  item['started_at']?.toString() ?? '')
                              ?.toLocal();
                          return ListTile(
                            dense: true,
                            leading: const Icon(Icons.visibility_outlined,
                                size: 18, color: NurbyColors.mutedForeground),
                            title: Text(
                                cameraName(item['camera_id']?.toString()),
                                style: const TextStyle(fontSize: 13)),
                            trailing: Text(
                              startedAt == null
                                  ? '--'
                                  : DateFormat('MMM d, HH:mm')
                                      .format(startedAt),
                              style: monoStyle,
                            ),
                          );
                        },
                      ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ClusterCard extends ConsumerWidget {
  const _ClusterCard({required this.suggestion});
  final FaceClusterSuggestion suggestion;

  Future<void> _name(BuildContext context, WidgetRef ref) async {
    final nameController = TextEditingController();
    final relationshipController = TextEditingController();
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: NurbyColors.cardElevated,
        title: const Text('Name this person'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: nameController,
              autofocus: true,
              decoration: const InputDecoration(labelText: 'Display name'),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: relationshipController,
              decoration: const InputDecoration(
                  labelText: 'Relationship (optional)',
                  hintText: 'e.g. neighbor, family'),
            ),
          ],
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Cancel')),
          TextButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Save')),
        ],
      ),
    );
    if (confirmed != true) return;
    final displayName = nameController.text.trim();
    if (displayName.isEmpty) return;
    try {
      final relationship = relationshipController.text.trim();
      await ref.read(personRepoProvider).nameCluster(
            suggestion.id,
            displayName,
            relationship: relationship.isEmpty ? null : relationship,
          );
      ref.invalidate(_suggestionsProvider);
      ref.invalidate(_peopleProvider);
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    }
  }

  Future<void> _ignore(BuildContext context, WidgetRef ref) async {
    try {
      await ref.read(personRepoProvider).ignoreCluster(suggestion.id);
      ref.invalidate(_suggestionsProvider);
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final repo = ref.watch(personRepoProvider);

    return SizedBox(
      width: 180,
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(10),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              ClipRRect(
                borderRadius: BorderRadius.circular(8),
                child: Image.network(
                  repo.clusterThumbnailUrl(suggestion.id),
                  height: 84,
                  width: double.infinity,
                  fit: BoxFit.cover,
                  errorBuilder: (_, __, ___) => Container(
                    height: 84,
                    color: NurbyColors.cardElevated,
                    child: const Icon(Icons.face_outlined,
                        color: NurbyColors.mutedForeground),
                  ),
                ),
              ),
              const SizedBox(height: 6),
              Text(
                suggestion.autoLabel ?? 'Unknown person',
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                    fontWeight: FontWeight.w600, fontSize: 13),
              ),
              Text('${suggestion.sightingCount} sightings',
                  style: monoStyle.copyWith(fontSize: 11)),
              if (suggestion.appearanceDescription != null)
                Expanded(
                  child: Text(
                    suggestion.appearanceDescription!,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                        color: NurbyColors.mutedForeground, fontSize: 11),
                  ),
                )
              else
                const Spacer(),
              Row(
                children: [
                  Expanded(
                    child: TextButton(
                      style: TextButton.styleFrom(
                        padding: EdgeInsets.zero,
                        minimumSize: const Size(0, 32),
                      ),
                      onPressed: () => _name(context, ref),
                      child: const Text('Name',
                          style: TextStyle(
                              color: NurbyColors.accent, fontSize: 13)),
                    ),
                  ),
                  Expanded(
                    child: TextButton(
                      style: TextButton.styleFrom(
                        padding: EdgeInsets.zero,
                        minimumSize: const Size(0, 32),
                      ),
                      onPressed: () => _ignore(context, ref),
                      child: const Text('Ignore',
                          style: TextStyle(
                              color: NurbyColors.mutedForeground,
                              fontSize: 13)),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
