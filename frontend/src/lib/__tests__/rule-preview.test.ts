import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { humanizeTemplate } from "@/lib/rule-preview";
import { RULE_TEMPLATES, type TemplateContext } from "@/lib/rule-templates";

// The system-rule templates live once, in shared/default_rules.py; read
// them from there so this test fails if the Python source and the preview
// renderer ever disagree.
const defaultRulesPy = readFileSync(
  path.resolve(__dirname, "../../../../shared/default_rules.py"),
  "utf8",
);
function pyString(name: string): string {
  const match = defaultRulesPy.match(new RegExp(`${name} = "([^"]+)"`));
  if (!match) throw new Error(`${name} not found in shared/default_rules.py`);
  return match[1];
}
const CAMERA_HEALTH_DEGRADED_MESSAGE = pyString("CAMERA_HEALTH_DEGRADED_MESSAGE");
const CAMERA_HEALTH_RECOVERED_MESSAGE = pyString("CAMERA_HEALTH_RECOVERED_MESSAGE");

const context: TemplateContext = { cameras: [], persons: [], telegramChannels: [] };

// Every message template that ships (gallery templates + the system
// rules) must render through humanizeTemplate with no raw braces and no
// bracketed pseudo-placeholders — those read like debug output on a card
// (issue #320; regression of the July F30/F48 fix).
function shippedTemplates(): string[] {
  const messages: string[] = [
    CAMERA_HEALTH_DEGRADED_MESSAGE,
    CAMERA_HEALTH_RECOVERED_MESSAGE,
  ];
  for (const template of RULE_TEMPLATES) {
    const actions = template.build(context).actions;
    for (const action of Array.isArray(actions) ? actions : [actions]) {
      if (action && typeof action === "object" && action.type === "notify" && typeof action.message === "string") {
        messages.push(action.message);
      }
    }
  }
  return messages;
}

describe("humanizeTemplate", () => {
  it("renders known tokens as friendly words", () => {
    expect(humanizeTemplate("Rule '{rule_name}' fired on {camera_name} at {timestamp_local}"))
      .toBe("Rule 'this rule' fired on the camera at the time");
  });

  it("upgrades tokens to real names when context is given", () => {
    expect(
      humanizeTemplate("Motion on {camera_name}", { cameraName: "Front Door", ruleName: "Door watch" }),
    ).toBe("Motion on Front Door");
    expect(
      humanizeTemplate("Rule '{rule_name}' fired", { ruleName: "Door watch" }),
    ).toBe("Rule 'Door watch' fired");
  });

  it("collapses unknown tokens to an ellipsis, never raw braces or brackets", () => {
    expect(humanizeTemplate("Camera health degraded on {camera_name}: {reason}"))
      .toBe("Camera health degraded on the camera: …");
    expect(humanizeTemplate("value {vars.custom_thing} end")).toBe("value … end");
  });

  it("leaves no placeholder artifacts in any shipped template", () => {
    for (const message of shippedTemplates()) {
      const rendered = humanizeTemplate(message);
      expect(rendered, message).not.toMatch(/\{|\}|[[\]]/);
    }
  });

  it("renders the system health rules as readable sentences", () => {
    expect(humanizeTemplate(CAMERA_HEALTH_DEGRADED_MESSAGE, { cameraName: "Front Door" }))
      .toBe("Camera health degraded on Front Door: …");
    expect(humanizeTemplate(CAMERA_HEALTH_RECOVERED_MESSAGE, { cameraName: "Front Door" }))
      .toBe("Camera health recovered on Front Door");
  });
});
