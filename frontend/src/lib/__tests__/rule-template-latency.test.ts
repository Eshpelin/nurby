import { describe, expect, it } from "vitest";

import { RULE_TEMPLATES } from "../rule-templates";

describe("two-lane alert latency contract", () => {
  it("puts the deterministic alert before after-hours verification", () => {
    const template = RULE_TEMPLATES.find((item) => item.key === "after-hours-office");
    expect(template).toBeDefined();
    const actions = template!.build(
      { cameras: [], persons: [], telegramChannels: [] },
      undefined,
    ).actions as Array<{ type: string; on_fail?: string }>;
    expect(actions.map((action) => action.type)).toEqual(["notify", "verify"]);
    expect(actions[1].on_fail).toBe("demote");
  });
});
