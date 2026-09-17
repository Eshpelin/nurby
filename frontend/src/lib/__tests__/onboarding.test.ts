import { describe, expect, it } from "vitest";
import { GOALS, goalsForPlace } from "@/lib/onboarding";

describe("goalsForPlace", () => {
  it("offers deliveries at home but after-hours only to business", () => {
    const home = goalsForPlace("home");
    const business = goalsForPlace("business");
    expect(home).toContain("deliveries");
    expect(home).not.toContain("after_hours");
    expect(business).toContain("after_hours");
    expect(business).not.toContain("deliveries");
  });

  it("always includes review as a no-setup option", () => {
    expect(goalsForPlace("home")).toContain("review");
    expect(goalsForPlace("business")).toContain("review");
  });

  it("only offers goals that have a defined recommendation", () => {
    for (const place of ["home", "business"] as const) {
      for (const goal of goalsForPlace(place)) {
        expect(GOALS[goal]).toBeDefined();
      }
    }
  });
});

describe("goal recommendations", () => {
  it("detection-only starters do not require an AI provider", () => {
    expect(GOALS.entrance.needs).toMatch(/No AI provider/i);
    expect(GOALS.deliveries.needs).toMatch(/No AI provider/i);
  });

  it("after-hours discloses it needs a vision AI provider", () => {
    expect(GOALS.after_hours.needs).toMatch(/AI provider/i);
  });

  it("review and explore point away from rule creation", () => {
    expect(GOALS.review.template).toBeUndefined();
    expect(GOALS.explore.template).toBeUndefined();
  });
});
