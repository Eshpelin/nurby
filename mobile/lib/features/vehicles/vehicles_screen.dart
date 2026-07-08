import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';

final _vehiclesProvider =
    FutureProvider<List<Map<String, dynamic>>>((ref) async {
  final j = await ref.watch(apiClientProvider).getJson('/api/vehicles');
  return (j as List? ?? [])
      .whereType<Map>()
      .map((v) => v.cast<String, dynamic>())
      .toList();
});

String _lastSeen(dynamic iso) {
  final t = DateTime.tryParse(iso?.toString() ?? '')?.toLocal();
  if (t == null) return 'never';
  final d = DateTime.now().difference(t);
  if (d.inMinutes < 1) return 'just now';
  if (d.inMinutes < 60) return '${d.inMinutes}m ago';
  if (d.inHours < 24) return '${d.inHours}h ago';
  if (d.inDays < 7) return '${d.inDays}d ago';
  return DateFormat('MMM d').format(t);
}

/// Recognized vehicles: plate, make/model, sightings; edit and delete.
class VehiclesScreen extends ConsumerWidget {
  const VehiclesScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final vehiclesAsync = ref.watch(_vehiclesProvider);

    return Scaffold(
      appBar: AppBar(title: const Text('Vehicles')),
      body: vehiclesAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Text(apiErrorMessage(e),
                style: const TextStyle(color: NurbyColors.mutedForeground)),
          ),
        ),
        data: (vehicles) => RefreshIndicator(
          onRefresh: () => ref.refresh(_vehiclesProvider.future),
          child: vehicles.isEmpty
              ? ListView(
                  physics: const AlwaysScrollableScrollPhysics(),
                  children: const [
                    Padding(
                      padding: EdgeInsets.only(top: 120),
                      child: Center(
                        child: Column(
                          children: [
                            Icon(Icons.directions_car_outlined,
                                size: 40, color: NurbyColors.mutedForeground),
                            SizedBox(height: 12),
                            Text(
                              'No vehicles recognized yet.\nEnable license '
                              'plate detection on a camera.',
                              textAlign: TextAlign.center,
                              style: TextStyle(
                                  color: NurbyColors.mutedForeground),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                )
              : ListView.builder(
                  physics: const AlwaysScrollableScrollPhysics(),
                  padding: const EdgeInsets.all(12),
                  itemCount: vehicles.length,
                  itemBuilder: (context, i) =>
                      _VehicleRow(vehicle: vehicles[i]),
                ),
        ),
      ),
    );
  }
}

class _VehicleRow extends ConsumerWidget {
  const _VehicleRow({required this.vehicle});
  final Map<String, dynamic> vehicle;

  String get _id => vehicle['id'].toString();

  Future<bool> _confirmDelete(BuildContext context) async {
    final plate = vehicle['license_plate']?.toString() ?? 'vehicle';
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: NurbyColors.cardElevated,
        title: const Text('Delete vehicle?'),
        content: Text('"$plate" and its sighting history will be removed.'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Cancel')),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Delete',
                style: TextStyle(color: NurbyColors.danger)),
          ),
        ],
      ),
    );
    return confirmed ?? false;
  }

  Future<void> _edit(BuildContext context, WidgetRef ref) async {
    final nickname =
        TextEditingController(text: vehicle['nickname']?.toString() ?? '');
    final plate = TextEditingController(
        text: vehicle['license_plate']?.toString() ?? '');
    final make =
        TextEditingController(text: vehicle['make']?.toString() ?? '');
    final model =
        TextEditingController(text: vehicle['model']?.toString() ?? '');
    final color =
        TextEditingController(text: vehicle['color']?.toString() ?? '');

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: NurbyColors.cardElevated,
        title: const Text('Edit vehicle'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                  controller: nickname,
                  decoration: const InputDecoration(labelText: 'Nickname')),
              const SizedBox(height: 12),
              TextField(
                  controller: plate,
                  decoration:
                      const InputDecoration(labelText: 'License plate')),
              const SizedBox(height: 12),
              TextField(
                  controller: make,
                  decoration: const InputDecoration(labelText: 'Make')),
              const SizedBox(height: 12),
              TextField(
                  controller: model,
                  decoration: const InputDecoration(labelText: 'Model')),
              const SizedBox(height: 12),
              TextField(
                  controller: color,
                  decoration: const InputDecoration(labelText: 'Color')),
            ],
          ),
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

    String? valueOf(TextEditingController c) {
      final v = c.text.trim();
      return v.isEmpty ? null : v;
    }

    try {
      await ref.read(apiClientProvider).patchJson('/api/vehicles/$_id', body: {
        'nickname': valueOf(nickname),
        'license_plate': valueOf(plate),
        'make': valueOf(make),
        'model': valueOf(model),
        'color': valueOf(color),
      });
      ref.invalidate(_vehiclesProvider);
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final api = ref.watch(apiClientProvider);
    final plate = vehicle['license_plate']?.toString();
    final descriptionParts = [
      vehicle['nickname']?.toString(),
      vehicle['color']?.toString(),
      vehicle['make']?.toString(),
      vehicle['model']?.toString(),
    ].whereType<String>().where((s) => s.isNotEmpty).toList();
    final sightings = vehicle['sighting_count'] as int? ?? 0;

    return Dismissible(
      key: ValueKey(_id),
      direction: DismissDirection.endToStart,
      confirmDismiss: (_) => _confirmDelete(context),
      onDismissed: (_) async {
        try {
          await ref.read(apiClientProvider).delete('/api/vehicles/$_id');
        } catch (e) {
          if (context.mounted) {
            ScaffoldMessenger.of(context)
                .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
          }
        } finally {
          ref.invalidate(_vehiclesProvider);
        }
      },
      background: Container(
        alignment: Alignment.centerRight,
        padding: const EdgeInsets.only(right: 20),
        margin: const EdgeInsets.only(bottom: 8),
        decoration: BoxDecoration(
          color: NurbyColors.danger.withValues(alpha: 0.25),
          borderRadius: BorderRadius.circular(12),
        ),
        child: const Icon(Icons.delete_outline, color: NurbyColors.danger),
      ),
      child: Card(
        margin: const EdgeInsets.only(bottom: 8),
        child: ListTile(
          onTap: () => _edit(context, ref),
          leading: ClipRRect(
            borderRadius: BorderRadius.circular(6),
            child: Image.network(
              api.mediaUrl('/api/vehicles/$_id/photo'),
              width: 64,
              height: 44,
              fit: BoxFit.cover,
              errorBuilder: (_, __, ___) => Container(
                width: 64,
                height: 44,
                color: NurbyColors.cardElevated,
                child: const Icon(Icons.directions_car_outlined,
                    size: 20, color: NurbyColors.mutedForeground),
              ),
            ),
          ),
          title: Row(
            children: [
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(
                  border: Border.all(color: NurbyColors.border),
                  borderRadius: BorderRadius.circular(6),
                  color: NurbyColors.cardElevated,
                ),
                child: Text(
                  plate ?? 'NO PLATE',
                  style: monoStyle.copyWith(
                    color: NurbyColors.foreground,
                    fontWeight: FontWeight.w600,
                    letterSpacing: 1.2,
                  ),
                ),
              ),
            ],
          ),
          subtitle: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (descriptionParts.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 3),
                  child: Text(
                    descriptionParts.join(' · '),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                        color: NurbyColors.foreground, fontSize: 13),
                  ),
                ),
              Padding(
                padding: const EdgeInsets.only(top: 3),
                child: Text(
                  '$sightings sightings · last seen '
                  '${_lastSeen(vehicle['last_seen_at'])}',
                  style: monoStyle,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
