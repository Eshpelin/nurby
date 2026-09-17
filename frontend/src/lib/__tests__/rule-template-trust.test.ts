import { describe, expect, it } from "vitest";
import {
  findTemplate,
  RULE_TEMPLATES,
  ruleIsConsequential,
  templateIsReviewFirst,
  type TemplateContext,
} from "@/lib/rule-templates";

const context: TemplateContext = { cameras: [], persons: [], telegramChannels: [] };

describe("workplace template evidence", () => {
  it("opens a review alert instead of billing a suspected guest", () => {
    const template = findTemplate("tailgate-guest-fee")!;
    const rule = template.build(context);
    if (!Array.isArray(rule.actions)) throw new Error("Expected a review action chain");
    expect(rule.actions).toHaveLength(1);
    expect(rule.actions[0].type).toBe("notify");
    expect(JSON.stringify(rule.actions)).not.toMatch(/api_call|charges|fee raised/i);
    expect(template.blurb).toContain("No fee is charged");
  });

  it("does not claim the sequence proves two distinct entrants", () => {
    const template = findTemplate("tailgate-badge-door")!;
    expect(template.blurb).toContain("may be the same person");
    expect(JSON.stringify(template.build(context).actions)).toContain("Possible");
  });
});

describe("review-first defaults (#192)", () => {
  it("builds a paused rule for every template that takes a real-world action", () => {
    // api_call/device/webhook/speak templates must land disabled.
    const consequential = RULE_TEMPLATES.filter((t) =>
      ruleIsConsequential(t.build(context)),
    );
    // At least the dock-dwell, mis-slotted-pallet and line-stopped recipes.
    expect(consequential.length).toBeGreaterThanOrEqual(3);
    for (const t of consequential) {
      expect(t.build(context).enabled, t.key).toBe(false);
      expect(templateIsReviewFirst(t, context), t.key).toBe(true);
    }
  });

  it("leaves informational (notify/telegram) templates enabled", () => {
    const informational = RULE_TEMPLATES.filter(
      (t) => !ruleIsConsequential(t.build(context)),
    );
    for (const t of informational) {
      expect(t.build(context).enabled, t.key).toBe(true);
      expect(templateIsReviewFirst(t, context), t.key).toBe(false);
    }
  });

  it("detects a consequential action hidden in a sequence on_timeout", () => {
    // The line-stoppage recipe opens a work order only in on_timeout.
    const lineStopped = findTemplate("line-stopped")!;
    const rule = lineStopped.build(context);
    expect(Array.isArray(rule.actions) ? rule.actions.length : 1).toBe(0);
    expect(ruleIsConsequential(rule)).toBe(true);
    expect(rule.enabled).toBe(false);
  });

  it("keeps the guest-fee review recipe enabled since it only notifies", () => {
    const guestFee = findTemplate("tailgate-guest-fee")!;
    expect(guestFee.build(context).enabled).toBe(true);
  });
});
