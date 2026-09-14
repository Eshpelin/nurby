import { describe, expect, it } from "vitest";
import { activeKind, ACTIVITY_KINDS } from "@/components/activity/ActivityFilterBar";

/**
 * Which chip is lit. Alerts and Recordings keep their own pages, so the
 * bar has to read the pathname as well as the query, or those two
 * always look like "All".
 */
describe("activeKind", () => {
  it("lights Alerts on the events page", () => {
    expect(activeKind("/events", null)).toBe("alerts");
  });

  it("lights Recordings on the recordings page", () => {
    expect(activeKind("/recordings", null)).toBe("recordings");
  });

  it("reads the kind from the query on /activity", () => {
    expect(activeKind("/activity", "incidents")).toBe("incidents");
    expect(activeKind("/activity", "recaps")).toBe("recaps");
  });

  it("falls back to All for an unknown kind", () => {
    expect(activeKind("/activity", "nonsense")).toBe("all");
    expect(activeKind("/activity", null)).toBe("all");
  });

  it("every chip has a distinct destination", () => {
    const hrefs = ACTIVITY_KINDS.map((k) => k.href);
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });

  it("every chip's destination resolves back to that chip", () => {
    // A chip that does not light itself when followed is the bug this
    // catches: the bar would show "All" after every click.
    for (const { kind, href } of ACTIVITY_KINDS) {
      const [path, query] = href.split("?");
      const k = new URLSearchParams(query ?? "").get("kind");
      expect(activeKind(path, k)).toBe(kind);
    }
  });
});
