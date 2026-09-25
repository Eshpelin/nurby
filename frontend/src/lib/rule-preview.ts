// Display-time rendering of rule message templates — the {token} strings
// the backend substitutes at fire time. One renderer for every surface
// that shows a rule as a sentence (rule cards, the events-panel detail,
// the builders' live preview) so token handling cannot drift per surface
// again. The July 2026 fix F30/F48 introduced display-time substitution;
// #320 regression-proofed it behind this module after the system-rule
// templates rendered as "the camera camera health degraded: [reason]".
//
// Known tokens get friendly words; an optional context upgrades them to
// real names. Unknown tokens collapse to an ellipsis: a preview cannot
// know runtime values, and raw braces or bracketed keys read like debug
// output on a card.

export interface TemplateContext {
  ruleName?: string;
  cameraName?: string | null;
}

const RULE_NAME = /\{\{?\s*rule_name\s*\}?\}/g;
const CAMERA_NAME = /\{\{?\s*camera_name\s*\}?\}/g;
const CAMERA_ID = /\{\{?\s*camera_id\s*\}?\}/g;
const TIMESTAMP = /\{\{?\s*timestamp(_local)?\s*\}?\}/g;
const UNKNOWN = /\{\s*[^{}]*\}/g;

export function humanizeTemplate(text: string, ctx?: TemplateContext | string): string {
  const options: TemplateContext =
    typeof ctx === "string" ? { ruleName: ctx } : (ctx ?? {});
  let out = text
    .replace(RULE_NAME, () => options.ruleName || "this rule")
    .replace(CAMERA_NAME, () => options.cameraName || "the camera")
    .replace(CAMERA_ID, () => options.cameraName || "the camera")
    .replace(TIMESTAMP, "the time");
  out = out.replace(UNKNOWN, "…");
  // Tidy the seams an ellipsis can leave behind.
  return out.replace(/\s{2,}/g, " ").replace(/\s+([:,;.!?])/g, "$1").trim();
}
