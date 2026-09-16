import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';
import '../../models/household_mode.dart';

/// Household mode (#184): home, away or night, for the whole house.
///
/// Rules gate on it, so this control is the difference between "alerts
/// all day" and "alerts that matter". It says how many rules the current
/// mode is keeping quiet, because a silent rule is otherwise
/// indistinguishable from a broken one.
class HouseholdModeCard extends ConsumerStatefulWidget {
  const HouseholdModeCard({super.key});

  @override
  ConsumerState<HouseholdModeCard> createState() => _HouseholdModeCardState();
}

class _HouseholdModeCardState extends ConsumerState<HouseholdModeCard> {
  // Set while a change is in flight, so the chip moves under the finger
  // rather than after a round trip.
  String? _pending;

  Future<void> _choose(String mode, HouseholdModeState state) async {
    if (mode == state.mode || _pending != null) return;
    setState(() => _pending = mode);
    try {
      await ref.read(householdRepoProvider).setMode(mode);
      ref.invalidate(householdModeProvider);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(apiErrorMessage(e))),
      );
    } finally {
      if (mounted) setState(() => _pending = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(householdModeProvider);
    final state = async.value;
    // Nothing to show until the first load lands. A skeleton here would
    // be more chrome than the control itself.
    if (state == null) return const SizedBox.shrink();

    final shown = _pending ?? state.mode;
    final active = state.modes.where((m) => m.key == shown).firstOrNull;

    return Card(
      margin: const EdgeInsets.fromLTRB(16, 4, 16, 8),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Household', style: Theme.of(context).textTheme.labelLarge),
            const SizedBox(height: 8),
            Row(
              children: [
                for (final m in state.modes) ...[
                  Expanded(
                    child: _ModeChip(
                      label: m.label,
                      selected: m.key == shown,
                      onTap: _pending != null ? null : () => _choose(m.key, state),
                    ),
                  ),
                  if (m != state.modes.last) const SizedBox(width: 6),
                ],
              ],
            ),
            if (active != null) ...[
              const SizedBox(height: 8),
              Text(
                active.hint,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
              ),
            ],
            if (state.silencedRuleCount > 0) ...[
              const SizedBox(height: 6),
              InkWell(
                onTap: () => context.push('/settings/alerts'),
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 2),
                  child: Text(
                    '${state.silencedRuleCount} rule'
                    '${state.silencedRuleCount == 1 ? ' is' : 's are'} paused '
                    'while ${active?.label ?? state.mode}',
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: NurbyColors.info,
                        ),
                  ),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _ModeChip extends StatelessWidget {
  const _ModeChip({required this.label, required this.selected, this.onTap});

  final String label;
  final bool selected;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Material(
      color: selected ? scheme.primary.withValues(alpha: 0.18) : Colors.transparent,
      borderRadius: BorderRadius.circular(8),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(8),
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 10),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(8),
            border: Border.all(
              color: selected ? scheme.primary : scheme.outlineVariant,
            ),
          ),
          alignment: Alignment.center,
          child: Text(
            label,
            style: TextStyle(
              fontSize: 13,
              fontWeight: selected ? FontWeight.w600 : FontWeight.w400,
              color: selected ? scheme.primary : scheme.onSurfaceVariant,
            ),
          ),
        ),
      ),
    );
  }
}
