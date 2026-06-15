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
}
