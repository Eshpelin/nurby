/**
 * Household mode (#184): home, away or night. One value for the whole
 * household, read by the rule engine once per tick. The wording here is
 * a fallback; the live control reads labels and hints from
 * GET /api/household/mode so the three clients cannot drift.
 */

export type HouseholdMode = "home" | "away" | "night";

export const HOUSEHOLD_MODES: HouseholdMode[] = ["home", "away", "night"];

export const MODE_LABELS: Record<HouseholdMode, string> = {
  home: "Home",
  away: "Away",
  night: "Night",
};

export interface ModeOption {
  key: HouseholdMode;
  label: string;
  hint: string;
}

export interface ModeChange {
  id: string;
  mode: HouseholdMode;
  previous_mode: HouseholdMode | null;
  source: "manual" | "agent" | "auto";
  changed_by_user_id: string | null;
  changed_by_name: string | null;
  note: string | null;
  changed_at: string;
}

export interface HouseholdModeState {
  mode: HouseholdMode;
  since: string | null;
  source: string | null;
  modes: ModeOption[];
  history: ModeChange[];
  silenced_rule_count: number;
}

/** Whether a rule with these conditions fires while the house is in `mode`.
 *  No `modes` key, or an empty one, means always. Mirrors
 *  shared/household_mode.py::rule_active_in. */
export function ruleActiveIn(
  conditions: Record<string, unknown> | null | undefined,
  mode: HouseholdMode,
): boolean {
  const modes = conditions?.modes;
  if (!Array.isArray(modes) || modes.length === 0) return true;
  return modes.includes(mode);
}

/** The mode names a rule is gated to, e.g. ["Away", "Night"]. Empty when
 *  the rule fires in every mode. Unknown keys are dropped rather than
 *  printed raw. */
export function gatedModeNames(
  conditions: Record<string, unknown> | null | undefined,
): string[] {
  const modes = conditions?.modes;
  if (!Array.isArray(modes)) return [];
  return modes
    .filter((m): m is HouseholdMode => typeof m === "string" && m in MODE_LABELS)
    .map((m) => MODE_LABELS[m]);
}

/** "Only while Away or Night", or null when the rule has no mode gate. */
export function modeGateLabel(
  conditions: Record<string, unknown> | null | undefined,
): string | null {
  const names = gatedModeNames(conditions);
  if (names.length === 0) return null;
  return `Only while ${names.join(" or ")}`;
}

/** What the badge says while the current mode is keeping the rule quiet.
 *  Names the mode that would wake it, so the badge is an instruction and
 *  not just a state. */
export function modePausedLabel(
  conditions: Record<string, unknown> | null | undefined,
): string | null {
  const names = gatedModeNames(conditions);
  if (names.length === 0) return null;
  return `Paused until ${names.join(" or ")}`;
}
