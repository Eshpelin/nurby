import { describe, expect, it } from "vitest";
import { suggestedPersonaForCameraName, type Persona } from "../camera-personas";

const personas = (ids: string[]): Persona[] => ids.map((id) => ({ id, label: id, hint: "", iconPath: "", patch: {} }));

describe("suggestedPersonaForCameraName", () => {
  it("suggests a front-door preset without applying it", () => {
    expect(suggestedPersonaForCameraName("Front Door", personas(["front-door"]))?.id).toBe("front-door");
    expect(suggestedPersonaForCameraName("Porch camera", personas(["front-door"]))?.id).toBe("front-door");
  });
  it("suggests driveway for garage names", () => {
    expect(suggestedPersonaForCameraName("Garage", personas(["driveway"]))?.id).toBe("driveway");
  });
  it("does not invent unavailable or unrelated suggestions", () => {
    expect(suggestedPersonaForCameraName("Front Door", personas(["baby-cam"]))).toBeNull();
    expect(suggestedPersonaForCameraName("Kitchen", personas(["front-door"]))).toBeNull();
  });
});
