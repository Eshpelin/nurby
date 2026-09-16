import { describe, it, expect } from "vitest";
import {
  HOUSEHOLD_MODES,
  MODE_LABELS,
  modeGateLabel,
  ruleActiveIn,
  type HouseholdMode,
} from "@/lib/household-mode";

describe("ruleActiveIn", () => {
  it("treats a rule with no modes as active everywhere", () => {
    for (const m of HOUSEHOLD_MODES) {
      expect(ruleActiveIn(null, m)).toBe(true);
      expect(ruleActiveIn(undefined, m)).toBe(true);
      expect(ruleActiveIn({}, m)).toBe(true);
      expect(ruleActiveIn({ modes: [] }, m)).toBe(true);
      expect(ruleActiveIn({ camera_id: "x" }, m)).toBe(true);
    }
  });

  it("gates a rule to only the modes it names", () => {
    const cond = { modes: ["away", "night"] };
    expect(ruleActiveIn(cond, "away")).toBe(true);
    expect(ruleActiveIn(cond, "night")).toBe(true);
    expect(ruleActiveIn(cond, "home")).toBe(false);
  });

  it("does not gate on a non-array modes value", () => {
    expect(ruleActiveIn({ modes: "away" }, "home")).toBe(true);
  });
});

describe("modeGateLabel", () => {
  it("returns null when the rule is not gated", () => {
    expect(modeGateLabel(null)).toBeNull();
    expect(modeGateLabel({})).toBeNull();
    expect(modeGateLabel({ modes: [] })).toBeNull();
  });

  it("names one mode", () => {
    expect(modeGateLabel({ modes: ["away"] })).toBe("Only while Away");
  });

  it("joins two modes the way a person would say it", () => {
    expect(modeGateLabel({ modes: ["away", "night"] })).toBe("Only while Away or Night");
  });

  it("drops a mode it does not recognise rather than printing the raw key", () => {
    expect(modeGateLabel({ modes: ["away", "vacation"] })).toBe("Only while Away");
    expect(modeGateLabel({ modes: ["vacation"] })).toBeNull();
  });
});

describe("the vocabulary", () => {
  it("labels every mode", () => {
    for (const m of HOUSEHOLD_MODES) {
      expect(MODE_LABELS[m as HouseholdMode]).toBeTruthy();
    }
  });
});

describe("modePausedLabel", () => {
  it("names the mode that would wake the rule, so the badge is actionable", async () => {
    const { modePausedLabel } = await import("@/lib/household-mode");
    expect(modePausedLabel({ modes: ["away"] })).toBe("Paused until Away");
    expect(modePausedLabel({ modes: ["away", "night"] })).toBe("Paused until Away or Night");
  });

  it("keeps the mode names capitalised", async () => {
    const { modePausedLabel } = await import("@/lib/household-mode");
    expect(modePausedLabel({ modes: ["away", "night"] })).toContain("Away");
    expect(modePausedLabel({ modes: ["away", "night"] })).toContain("Night");
  });

  it("returns null for an ungated rule", async () => {
    const { modePausedLabel } = await import("@/lib/household-mode");
    expect(modePausedLabel(null)).toBeNull();
    expect(modePausedLabel({ modes: [] })).toBeNull();
  });
});
