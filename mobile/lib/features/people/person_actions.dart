import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';
import 'package:intl/intl.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../models/models.dart';

/// Person operations mobile lacked (issue #171): merge, add a face
/// sample, set the photo from a real sighting.

/// Merge [source] into [target].
///
/// This is the one destructive person operation, and it is not
/// reversible: the source is gone afterwards and everything it had now
/// belongs to the target. So the confirmation names both sides, says
/// which one survives, and asks the person to type nothing but read.
Future<bool> confirmMerge(
    BuildContext context, WidgetRef ref, Person target, Person source) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      backgroundColor: NurbyColors.cardElevated,
      title: const Text('Merge two people?'),
      content: Text.rich(TextSpan(children: [
        const TextSpan(text: 'Everything about '),
        TextSpan(
            text: source.displayName,
            style: const TextStyle(fontWeight: FontWeight.w600)),
        const TextSpan(text: ' will move into '),
        TextSpan(
            text: target.displayName,
            style: const TextStyle(fontWeight: FontWeight.w600)),
        TextSpan(
            text: '. ${source.displayName} will no longer exist as a '
                'separate person. This cannot be undone.'),
      ])),
      actions: [
        TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('Cancel')),
        TextButton(
          onPressed: () => Navigator.pop(ctx, true),
          child: Text('Merge into ${target.displayName}',
              style: const TextStyle(color: NurbyColors.danger)),
        ),
      ],
    ),
  );
  if (ok != true) return false;
  try {
    await ref.read(personRepoProvider).merge(targetId: target.id, sourceId: source.id);
    return true;
  } catch (e) {
    if (context.mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
    }
    return false;
  }
}

/// Pick which other person to merge into [source].
class MergePickerSheet extends StatelessWidget {
  const MergePickerSheet({super.key, required this.source, required this.others});

  final Person source;
  final List<Person> others;

  @override
  Widget build(BuildContext context) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 4),
              child: Text('Merge ${source.displayName} into',
                  style: const TextStyle(fontWeight: FontWeight.w600)),
            ),
            const Padding(
              padding: EdgeInsets.fromLTRB(16, 0, 16, 8),
              child: Text(
                'Pick the one that should survive. Usually the one with '
                'the right name.',
                style: TextStyle(
                    fontSize: 12, color: NurbyColors.mutedForeground),
              ),
            ),
            for (final p in others)
              ListTile(
                title: Text(p.displayName),
                subtitle: p.relationship == null
                    ? null
                    : Text(p.relationship!,
                        style: const TextStyle(
                            fontSize: 12, color: NurbyColors.mutedForeground)),
                onTap: () => Navigator.pop(context, p),
              ),
          ],
        ),
      );
}

/// Add a face sample from the photo library.
Future<void> addFaceFromLibrary(
    BuildContext context, WidgetRef ref, Person person) async {
  final picked = await ImagePicker().pickImage(
    source: ImageSource.gallery,
    // A face crop does not need a 12 MP original, and the upload is
    // over the household's own network which may be slow.
    maxWidth: 1600,
    imageQuality: 88,
  );
  if (picked == null || !context.mounted) return;
  try {
    await ref.read(personRepoProvider).addFace(person.id, picked.path);
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Added a face for ${person.displayName}.')));
    }
  } catch (e) {
    if (context.mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
    }
  }
}

final photoCandidatesProvider =
    FutureProvider.family<List<Map<String, dynamic>>, String>(
        (ref, personId) => ref.watch(personRepoProvider).photoCandidates(personId));

/// Choose a person's photo from real sightings.
class PhotoCandidatesSheet extends ConsumerWidget {
  const PhotoCandidatesSheet({super.key, required this.person});

  final Person person;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(photoCandidatesProvider(person.id));
    final obsRepo = ref.read(observationRepoProvider);

    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('A photo for ${person.displayName}',
                style: const TextStyle(fontWeight: FontWeight.w600)),
            const SizedBox(height: 4),
            const Text('From the times a camera actually saw them.',
                style: TextStyle(
                    fontSize: 12, color: NurbyColors.mutedForeground)),
            const SizedBox(height: 12),
            async.when(
              loading: () => const LinearProgressIndicator(),
              error: (e, _) => Text(apiErrorMessage(e),
                  style: const TextStyle(
                      fontSize: 12, color: NurbyColors.mutedForeground)),
              data: (cands) => cands.isEmpty
                  ? const Text('No clear sightings yet.',
                      style: TextStyle(
                          fontSize: 12, color: NurbyColors.mutedForeground))
                  : SizedBox(
                      height: 240,
                      child: GridView.builder(
                        gridDelegate:
                            const SliverGridDelegateWithFixedCrossAxisCount(
                          crossAxisCount: 3,
                          mainAxisSpacing: 6,
                          crossAxisSpacing: 6,
                        ),
                        itemCount: cands.length,
                        itemBuilder: (_, i) {
                          final c = cands[i];
                          final obsId = c['observation_id'] as String;
                          return InkWell(
                            onTap: () async {
                              try {
                                await ref
                                    .read(personRepoProvider)
                                    .setPhotoFromObservation(person.id, obsId);
                                if (context.mounted) Navigator.pop(context, true);
                              } catch (e) {
                                if (context.mounted) {
                                  ScaffoldMessenger.of(context).showSnackBar(
                                      SnackBar(content: Text(apiErrorMessage(e))));
                                }
                              }
                            },
                            child: Column(
                              children: [
                                Expanded(
                                  child: ClipRRect(
                                    borderRadius: BorderRadius.circular(6),
                                    child: Image.network(
                                      obsRepo.thumbnailUrl(obsId),
                                      fit: BoxFit.cover,
                                      width: double.infinity,
                                      errorBuilder: (_, __, ___) =>
                                          const ColoredBox(
                                              color: NurbyColors.cardElevated),
                                    ),
                                  ),
                                ),
                                if (c['started_at'] != null)
                                  Text(
                                    DateFormat('MMM d').format(
                                        DateTime.parse('${c['started_at']}')
                                            .toLocal()),
                                    style: const TextStyle(
                                        fontSize: 10,
                                        color: NurbyColors.mutedForeground),
                                  ),
                              ],
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
