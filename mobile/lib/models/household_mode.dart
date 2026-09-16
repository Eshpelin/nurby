/// Household mode (#184): home, away or night, for the whole house.
///
/// Rules gate on it through `conditions.modes`. A rule without that key
/// fires in every mode, which is every rule written before this existed.
/// Labels and hints come from the server so the three clients cannot
/// drift; the constants here are only the fallback and the ordering.
library;

const kHouseholdModes = <String>['home', 'away', 'night'];

const kModeLabels = <String, String>{
  'home': 'Home',
  'away': 'Away',
  'night': 'Night',
};

class ModeOption {
  const ModeOption({required this.key, required this.label, required this.hint});

  final String key;
  final String label;
  final String hint;

  factory ModeOption.fromJson(Map<String, dynamic> j) => ModeOption(
        key: j['key'] as String,
        label: j['label'] as String? ?? j['key'] as String,
        hint: j['hint'] as String? ?? '',
      );
}

class ModeChange {
  const ModeChange({
    required this.id,
    required this.mode,
    required this.previousMode,
    required this.source,
    required this.changedByName,
    required this.note,
    required this.changedAt,
  });

  final String id;
  final String mode;
  final String? previousMode;
  final String source;
  final String? changedByName;
  final String? note;
  final DateTime changedAt;

  factory ModeChange.fromJson(Map<String, dynamic> j) => ModeChange(
        id: j['id'] as String,
        mode: j['mode'] as String,
        previousMode: j['previous_mode'] as String?,
        source: j['source'] as String? ?? 'manual',
        changedByName: j['changed_by_name'] as String?,
        note: j['note'] as String?,
        changedAt:
            DateTime.tryParse(j['changed_at'] as String? ?? '')?.toLocal() ??
                DateTime.now(),
      );
}

class HouseholdModeState {
  const HouseholdModeState({
    required this.mode,
    required this.since,
    required this.source,
    required this.modes,
    required this.history,
    required this.silencedRuleCount,
  });

  final String mode;
  final DateTime? since;
  final String? source;
  final List<ModeOption> modes;
  final List<ModeChange> history;
  final int silencedRuleCount;

  ModeOption? get active {
    for (final m in modes) {
      if (m.key == mode) return m;
    }
    return null;
  }

  HouseholdModeState copyWith({String? mode}) => HouseholdModeState(
        mode: mode ?? this.mode,
        since: since,
        source: source,
        modes: modes,
        history: history,
        silencedRuleCount: silencedRuleCount,
      );

  factory HouseholdModeState.fromJson(Map<String, dynamic> j) =>
      HouseholdModeState(
        mode: j['mode'] as String? ?? 'home',
        since: DateTime.tryParse(j['since'] as String? ?? '')?.toLocal(),
        source: j['source'] as String?,
        modes: (j['modes'] as List? ?? const [])
            .whereType<Map>()
            .map((m) => ModeOption.fromJson(m.cast<String, dynamic>()))
            .toList(),
        history: (j['history'] as List? ?? const [])
            .whereType<Map>()
            .map((h) => ModeChange.fromJson(h.cast<String, dynamic>()))
            .toList(),
        silencedRuleCount: (j['silenced_rule_count'] as num?)?.toInt() ?? 0,
      );
}

/// Whether a rule with these conditions fires while the house is in [mode].
/// No `modes` key, or an empty one, means always. Mirrors
/// shared/household_mode.py::rule_active_in.
bool ruleActiveIn(Map<String, dynamic>? conditions, String mode) {
  final modes = conditions?['modes'];
  if (modes is! List || modes.isEmpty) return true;
  return modes.contains(mode);
}

/// The mode names a rule is gated to, e.g. ['Away', 'Night']. Empty when
/// the rule fires in every mode. Unknown keys are dropped rather than
/// shown raw.
List<String> gatedModeNames(Map<String, dynamic>? conditions) {
  final modes = conditions?['modes'];
  if (modes is! List) return const [];
  return modes
      .whereType<String>()
      .where(kModeLabels.containsKey)
      .map((m) => kModeLabels[m]!)
      .toList();
}

/// 'Only while Away or Night', or null when the rule has no mode gate.
String? modeGateLabel(Map<String, dynamic>? conditions) {
  final names = gatedModeNames(conditions);
  if (names.isEmpty) return null;
  return 'Only while ${names.join(' or ')}';
}

/// What the badge says while the current mode keeps the rule quiet. Names
/// the mode that would wake it, so the badge is an instruction and not
/// just a state.
String? modePausedLabel(Map<String, dynamic>? conditions) {
  final names = gatedModeNames(conditions);
  if (names.isEmpty) return null;
  return 'Paused until ${names.join(' or ')}';
}
