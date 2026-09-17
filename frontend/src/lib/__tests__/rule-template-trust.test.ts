import { describe, expect, it } from "vitest";
import { findTemplate, type TemplateContext } from "@/lib/rule-templates";

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
