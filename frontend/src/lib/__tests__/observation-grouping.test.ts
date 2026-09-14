import { describe, expect, it } from "vitest";
import { groupKey, coalesceObservations, isObservationGroup } from "@/lib/observation-grouping";

/**
 * Grouping decides what the dashboard shows as one thing. Getting it
 * wrong either splits one person's visit into twelve cards or merges two
 * different people into one, and neither is visible in a build.
 */
type Obs = Parameters<typeof groupKey>[0];

function obs(over: Partial<Obs> = {}): Obs {
  return {
    id: "o1",
    camera_id: "cam-1",
    started_at: "2026-09-14T10:00:00Z",
    object_detections: { objects: [] },
    person_detections: { faces: [] },
    ...over,
  } as Obs;
}

describe("groupKey", () => {
  it("puts a named person above everything else", () => {
    const k = groupKey(obs({
      person_detections: { faces: [{ person_name: "Sam", cluster_id: "c1" }] },
      object_detections: { objects: [{ label: "person" }] },
    } as Partial<Obs>));
    expect(k).toBe("cam-1|p:Sam");
  });

  it("sorts names so the same two people always share a key", () => {
    const a = groupKey(obs({ person_detections: { faces: [{ person_name: "Sam" }, { person_name: "Alex" }] } } as Partial<Obs>));
    const b = groupKey(obs({ person_detections: { faces: [{ person_name: "Alex" }, { person_name: "Sam" }] } } as Partial<Obs>));
    expect(a).toBe(b);
  });

  it("uses the cluster when a face has no name", () => {
    expect(groupKey(obs({ person_detections: { faces: [{ cluster_id: "c9" }] } } as Partial<Obs>)))
      .toBe("cam-1|c:c9");
  });

  it("falls back to unknown for a face with neither", () => {
    expect(groupKey(obs({ person_detections: { faces: [{}] } } as Partial<Obs>)))
      .toBe("cam-1|unknown");
  });

  it("ignores plates in the object signature", () => {
    // Plates are surfaced separately; letting one into the key would
    // split a car's visit every time the plate read flickered.
    expect(groupKey(obs({ object_detections: { objects: [{ label: "car" }, { label: "license_plate" }] } } as Partial<Obs>)))
      .toBe("cam-1|o:car");
  });

  it("never merges across cameras", () => {
    const a = groupKey(obs({ camera_id: "cam-1" }));
    const b = groupKey(obs({ camera_id: "cam-2" }));
    expect(a).not.toBe(b);
  });

  it("falls back to motion when nothing was detected", () => {
    expect(groupKey(obs())).toBe("cam-1|motion");
  });
});

describe("coalesceObservations", () => {
  const sam = (id: string, at: string) =>
    obs({ id, started_at: at, person_detections: { faces: [{ person_name: "Sam" }] } } as Partial<Obs>);

  it("merges the same person on the same camera inside the window", () => {
    const out = coalesceObservations(
      [sam("a", "2026-09-14T10:00:00Z"), sam("b", "2026-09-14T10:00:30Z")] as Parameters<typeof coalesceObservations>[0],
      60_000,
    );
    expect(out).toHaveLength(1);
    expect(isObservationGroup(out[0])).toBe(true);
  });

  it("keeps them apart once the gap exceeds the window", () => {
    const out = coalesceObservations(
      [sam("a", "2026-09-14T10:00:00Z"), sam("b", "2026-09-14T10:05:00Z")] as Parameters<typeof coalesceObservations>[0],
      60_000,
    );
    expect(out).toHaveLength(2);
  });

  it("a zero window merges nothing", () => {
    const rows = [sam("a", "2026-09-14T10:00:00Z"), sam("b", "2026-09-14T10:00:01Z")] as Parameters<typeof coalesceObservations>[0];
    expect(coalesceObservations(rows, 0)).toHaveLength(2);
  });
});
