/** Shared camera-config types, used by the camera page and its
 * extracted section components. */

export interface PTZPreset {
  token: string;
  name: string;
}

export interface MotionZone {
  name: string;
  points: number[][];
  type: "zone" | "include" | "exclude" | "loiter" | "tripwire" | "veto" | "signal";
  // Seconds before a loiter zone fires. Ignored for other types.
  loiter_threshold_seconds?: number;
  // Direction filter for tripwires. "any" | "in" | "out".
  direction?: string;
  // Signal zones only. Lamp sample points (auto-derived from the box +
  // orientation), and the captured per-state brightness calibration.
  orientation?: "vertical" | "horizontal";
  lamps?: { color: "red" | "amber" | "green"; point: number[]; r?: number }[];
  // calibration[state][lampColor] = that lamp's brightness when state was lit.
  calibration?: Record<string, Record<string, number>>;
}
