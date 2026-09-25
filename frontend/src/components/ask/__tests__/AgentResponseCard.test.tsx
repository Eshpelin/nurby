import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("../CitationChip", () => ({
  default: () => <button type="button" aria-label="Open citation">citation</button>,
}));

import { renderAnswer, traceProgressLabel } from "../AgentResponseCard";

describe("renderAnswer", () => {
  it("turns valid observation tokens into citation controls", () => {
    const id = "123e4567-e89b-12d3-a456-426614174000";
    const html = renderToStaticMarkup(<>{renderAnswer(`Seen [obs:${id}]`, [
      { kind: "observation", id },
    ])}</>);
    expect(html).toContain("Open citation");
  });

  it("removes invalid observation tokens instead of showing debug text", () => {
    const html = renderToStaticMarkup(<>{renderAnswer("Seen [obs:not-a-real-id]", [])}</>);
    expect(html).not.toContain("obs:");
    expect(html).toContain("Seen");
  });

  it("turns trace tool names into human-readable progress", () => {
    expect(traceProgressLabel([{ name: "get_camera_layout", kind: "tool", done: false }]))
      .toBe("Checking which cameras are available");
  });
});
