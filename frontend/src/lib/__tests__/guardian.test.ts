import { describe, expect, it } from "vitest";
import { dayLabel, HANDOVER_LABELS, isStaffConfirmed, NOTIFY_CHANNELS } from "@/lib/guardian";

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

describe("isStaffConfirmed", () => {
  it("is true only for an explicit staff-confirmed handover", () => {
    expect(isStaffConfirmed({ handover_state: "confirmed" })).toBe(true);
    expect(isStaffConfirmed({ staff_confirmed: true })).toBe(true);
  });

  it("never treats an inferred pickup as confirmed", () => {
    // A camera-only inference, even with an approved-registry match, is not
    // a confirmed handover (#191).
    expect(isStaffConfirmed({ handover_state: "possible" })).toBe(false);
    expect(isStaffConfirmed({ handover_state: "approved_match" })).toBe(false);
    expect(isStaffConfirmed({ handover_state: "corrected" })).toBe(false);
    expect(isStaffConfirmed({})).toBe(false);
  });
});

describe("HANDOVER_LABELS", () => {
  it("only the confirmed state names a staff confirmation", () => {
    expect(HANDOVER_LABELS.possible.toLowerCase()).not.toContain("confirmed by staff");
    expect(HANDOVER_LABELS.approved_match.toLowerCase()).not.toContain("confirmed by staff");
    expect(HANDOVER_LABELS.confirmed).toBe("Pickup confirmed by staff");
  });
});
