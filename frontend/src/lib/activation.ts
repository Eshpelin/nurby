// Verified first-useful-result client types (#193 / #204 phase 2).
// Mirrors shared/activation.py. A saved goal or a scaffolded draft is never
// activation. Only `verified` may present success.

export type ActivationStepKey = "configured" | "tested" | "confirmed";

export interface ActivationStepView {
  key: ActivationStepKey;
  done: boolean;
  synthetic: boolean;
}

export interface ActivationView {
  goal: string;
  event_id?: string | null;
  rule_id: string | null;
  camera_id: string | null;
  draft_rule_id: string | null;
  steps: ActivationStepView[];
  verified: boolean;
  next_step: ActivationStepKey | null;
  test_kind: "synthetic" | "real" | null;
  seconds_to_first_useful: number | null;
}

export interface ActivationList {
  milestones: ActivationView[];
}

// Goals that can be driven to a verified detection result. Kept in sync
// with shared/activation.py GOAL_STARTER.
export const DETECTION_GOALS = new Set(["entrance", "deliveries", "after_hours"]);

export const STEP_LABELS: Record<ActivationStepKey, { title: string; detail: string }> = {
  configured: {
    title: "Configured",
    detail: "An enabled rule points at a camera and has a way to reach you. This does not prove it works.",
  },
  tested: {
    title: "Tested with a real event",
    detail: "Trigger the camera yourself. The alert has to actually arrive.",
  },
  confirmed: {
    title: "Confirmed useful",
    detail: "Open the exact clip and confirm it showed what you needed.",
  },
};

export function milestoneForGoal(list: ActivationList | null, goal: string): ActivationView | null {
  return list?.milestones.find((m) => m.goal === goal) ?? null;
}
