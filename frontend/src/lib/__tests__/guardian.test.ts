import { describe, expect, it } from "vitest";
import { dayLabel, NOTIFY_CHANNELS } from "@/lib/guardian";

describe("dayLabel", () => {
  it("says Today and Yesterday rather than a date", () => {
    const now = new Date();
    const yest = new Date(now);
    yest.setDate(now.getDate() - 1);
    expect(dayLabel(now.toISOString())).toBe("Today");
    expect(dayLabel(yest.toISOString())).toBe("Yesterday");
  });

  it("names the weekday for anything older", () => {
    const old = new Date();
    old.setDate(old.getDate() - 5);
    const label = dayLabel(old.toISOString());
    expect(label).not.toBe("Today");
    expect(label).not.toBe("Yesterday");
    expect(label.length).toBeGreaterThan(3);
  });
});

describe("NOTIFY_CHANNELS", () => {
  it("matches the three the backend accepts", () => {
    // entitlements.NOTIFY_CHANNELS = ("telegram", "email", "in_app").
    // A fourth here would render a switch that writes a key the server
    // drops.
    expect(NOTIFY_CHANNELS.map((c) => c.key).sort()).toEqual(["email", "in_app", "telegram"]);
  });
});
