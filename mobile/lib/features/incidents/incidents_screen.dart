import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../models/models.dart';

/// Incidents, newest activity first. The bool key is "open only".
final incidentsListProvider =
    FutureProvider.family<List<Incident>, bool>((ref, openOnly) => ref
        .watch(incidentRepoProvider)
        .list(finalized: openOnly ? false : null));

/// How an incident's signature should read to a person.
///
/// The backend keys a subject by the strongest evidence it had, so the
/// same field is a person's name, a cluster id, or a YOLO label
/// depending on kind. Rendering the raw key would show a household a
/// uuid and call it a subject.
String incidentTitle(Incident i) {
  switch (i.signatureKind) {
    case 'person':
      return i.signatureKey.split(',').join(', ');
    case 'cluster':
      final short = i.signatureKey.split(',').first;
      return 'Recurring stranger ${short.substring(0, short.length.clamp(0, 8))}';
    case 'body':
      return 'Unrecognized person (matched by appearance)';
    case 'unknown':
      return 'Unknown person';
    case 'object':
      final labels = i.signatureKey.split(',');
      if (labels.length == 1) return _capitalize(labels.first);
      return '${_capitalize(labels.first)} and ${labels.length - 1} more';
    default:
      return 'Motion';
  }
}

String _capitalize(String s) =>
    s.isEmpty ? s : '${s[0].toUpperCase()}${s.substring(1)}';

String formatDuration(Duration d) {
  if (d.inSeconds < 60) return '${d.inSeconds}s';
  if (d.inMinutes < 60) return '${d.inMinutes}m';
  final hours = d.inHours;
  final minutes = d.inMinutes.remainder(60);
  return minutes == 0 ? '${hours}h' : '${hours}h ${minutes}m';
}

class IncidentsScreen extends ConsumerStatefulWidget {
  const IncidentsScreen({super.key, this.embedded = false});

  /// Rendered inside the Activity screen: no Scaffold, no app bar.
  final bool embedded;

  @override
  ConsumerState<IncidentsScreen> createState() => _IncidentsScreenState();
}

class _IncidentsScreenState extends ConsumerState<IncidentsScreen> {
  bool _openOnly = false;

  @override
  Widget build(BuildContext context) {
    final list = ref.watch(incidentsListProvider(_openOnly));
    final cameras = ref.watch(camerasProvider).value ?? const <Camera>[];
    final names = {for (final c in cameras) c.id: c.name};

    final body = RefreshIndicator(
        onRefresh: () async => ref.invalidate(incidentsListProvider(_openOnly)),
        child: list.when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => _Retry(
            message: apiErrorMessage(e),
            onRetry: () => ref.invalidate(incidentsListProvider(_openOnly)),
          ),
          data: (items) => items.isEmpty
              ? _Empty(
                  icon: Icons.inbox_outlined,
                  title: _openOnly ? 'Nothing happening now' : 'No incidents yet',
                  detail: _openOnly
                      ? 'Open incidents appear here while a subject is still around.'
                      : 'Nurby groups repeat sightings of the same subject into one incident.',
                )
              : ListView.builder(
                  itemCount: items.length,
                  itemBuilder: (_, i) =>
                      _IncidentTile(items[i], names[items[i].cameraId]),
                ),
        ),
      );
    if (widget.embedded) return body;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Incidents'),
        actions: [
          IconButton(
            tooltip: _openOnly ? 'Showing open only' : 'Showing all',
            icon: Icon(_openOnly ? Icons.filter_alt : Icons.filter_alt_outlined),
            onPressed: () => setState(() => _openOnly = !_openOnly),
          ),
        ],
      ),
      body: body,
    );
  }
}

class _IncidentTile extends StatelessWidget {
  const _IncidentTile(this.incident, this.cameraName);

  final Incident incident;
  final String? cameraName;

  @override
  Widget build(BuildContext context) {
    final time = DateFormat('MMM d, HH:mm').format(incident.startedAt);
    final open = !incident.finalized;

    return Card(
      margin: const EdgeInsets.fromLTRB(12, 6, 12, 0),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                if (open)
                  Container(
                    width: 8,
                    height: 8,
                    margin: const EdgeInsets.only(right: 8),
                    decoration: const BoxDecoration(
                      color: NurbyColors.accent,
                      shape: BoxShape.circle,
                    ),
                  ),
                Expanded(
                  child: Text(
                    incidentTitle(incident),
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                ),
                if (incident.occurrenceCount > 1)
                  Text('${incident.occurrenceCount}x',
                      style: const TextStyle(
                          fontSize: 12, color: NurbyColors.mutedForeground)),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              [
                if (cameraName != null) cameraName!,
                time,
                formatDuration(incident.duration),
              ].join(' · '),
              style: const TextStyle(
                  fontSize: 12, color: NurbyColors.mutedForeground),
            ),
            if (incident.summaryText != null) ...[
              const SizedBox(height: 6),
              Text(incident.summaryText!, style: const TextStyle(fontSize: 13)),
            ],
          ],
        ),
      ),
    );
  }
}

class _Empty extends StatelessWidget {
  const _Empty({required this.icon, required this.title, required this.detail});

  final IconData icon;
  final String title;
  final String detail;

  @override
  Widget build(BuildContext context) => ListView(
        children: [
          const SizedBox(height: 96),
          Icon(icon, size: 40, color: NurbyColors.mutedForeground),
          const SizedBox(height: 12),
          Center(
            child: Text(title,
                style: const TextStyle(fontWeight: FontWeight.w600)),
          ),
          const SizedBox(height: 6),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 40),
            child: Text(detail,
                textAlign: TextAlign.center,
                style: const TextStyle(
                    fontSize: 12, color: NurbyColors.mutedForeground)),
          ),
        ],
      );
}

class _Retry extends StatelessWidget {
  const _Retry({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) => ListView(
        children: [
          const SizedBox(height: 96),
          Center(
            child: Text(message,
                textAlign: TextAlign.center,
                style: const TextStyle(color: NurbyColors.mutedForeground)),
          ),
          const SizedBox(height: 12),
          Center(
            child: OutlinedButton(onPressed: onRetry, child: const Text('Retry')),
          ),
        ],
      );
}
