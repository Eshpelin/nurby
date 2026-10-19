import {
  CAMERA_BRANDS,
  brandNotes,
  brandSteps,
  findBrand,
  templateLabel,
  validateCameraBrands,
} from "@/lib/camera-brands";
import { describe, expect, it } from "vitest";

describe("camera brand data", () => {
  it("passes the locale-coverage contract", () => {
    expect(validateCameraBrands()).toEqual([]);
  });

  it("every brand keeps an English source and technical template URLs", () => {
    expect(CAMERA_BRANDS.length).toBeGreaterThan(20);
    for (const brand of CAMERA_BRANDS) {
      expect(brand.steps.length).toBeGreaterThan(0);
      for (const template of brand.templates) {
        expect(template.url).toMatch(/^rtsps?:\/\//);
      }
    }
  });

  it("serves Spanish when asked and English otherwise", () => {
    const hikvision = findBrand("hikvision")!;
    expect(brandSteps(hikvision, "es")[0]).not.toBe(
      brandSteps(hikvision, "en")[0],
    );
    // Unknown locales fall back to the English source.
    expect(brandSteps(hikvision, "fr")).toEqual(brandSteps(hikvision, "en"));
    expect(brandSteps(hikvision, null)).toEqual(brandSteps(hikvision, "en"));
    expect(templateLabel(hikvision.templates[0], "es")).toBe(
      "Flujo principal",
    );
    // Technical tokens (subtype=0) survive translation.
    expect(brandNotes(findBrand("dahua")!, "es")[0]).toContain("subtype=0");
  });
});
