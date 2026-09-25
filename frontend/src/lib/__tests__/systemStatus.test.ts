import { describe, expect, it } from "vitest";
import { computeSystemStatus } from "@/lib/systemStatus";

const base = { workersDown: [], degraded: [], wsStatus: "connected", aiOffline: false };

describe("computeSystemStatus", () => {
  it("is healthy when everything is up", () => {
    const s = computeSystemStatus(base);
    expect(s.level).toBe("ok");
    expect(s.label).toBe("All systems live");
    expect(s.detail).toBe("");
  });

  it("stays red for a stopped worker when real cameras exist", () => {
    const s = computeSystemStatus({ ...base, workersDown: ["video ingestion"], hasRealCameras: true });
    expect(s.level).toBe("down");
    expect(s.label).toBe("Not recording");
  });

  it("calms the banner when nothing but the demo camera exists (#318)", () => {
    // A fresh install with the workers genuinely stopped used to open on
    // a red "Not recording" alarm when the real next step was adding a
    // camera.
    const s = computeSystemStatus({ ...base, workersDown: ["video ingestion", "AI perception"], hasRealCameras: false });
    expect(s.level).toBe("ok");
    expect(s.label).toBe("No cameras yet");
    expect(s.detail).toMatch(/Add a camera or try the demo/);
  });

  it("defaults to alarm semantics while camera truth is unknown", () => {
    // Only a confirmed "no real cameras" may calm the message; an unknown
    // must never mask a real outage.
    const s = computeSystemStatus({ ...base, workersDown: ["video ingestion"] });
    expect(s.level).toBe("down");
  });

  it("treats a stopped worker as the most severe, over everything else", () => {
    const s = computeSystemStatus({ workersDown: ["video ingestion"], degraded: [{ label: "x" }], wsStatus: "reconnecting", aiOffline: true });
    expect(s.level).toBe("down");
    expect(s.label).toBe("Not recording");
    expect(s.detail).toMatch(/won't fire/);
  });

  it("reports AI offline above a stale live relay", () => {
    const s = computeSystemStatus({ ...base, aiOffline: true, wsStatus: "reconnecting" });
    expect(s.level).toBe("warn");
    expect(s.label).toBe("AI offline");
  });

  it("distinguishes reconnecting (warn) from disconnected (down)", () => {
    expect(computeSystemStatus({ ...base, wsStatus: "reconnecting" })).toMatchObject({ level: "warn", label: "Reconnecting" });
    expect(computeSystemStatus({ ...base, wsStatus: "disconnected" })).toMatchObject({ level: "down", label: "Live paused" });
  });

  it("surfaces a degraded component last, with its detail", () => {
    const s = computeSystemStatus({ ...base, degraded: [{ label: "Face model", detail: "failed to load" }] });
    expect(s.level).toBe("warn");
    expect(s.label).toBe("Degraded");
    expect(s.detail).toMatch(/Face model/);
    expect(s.detail).toMatch(/failed to load/);
  });

  it("only ever emits one verdict, never a pile of them", () => {
    // The whole point: pluralised worker phrasing stays one sentence.
    const s = computeSystemStatus({ ...base, workersDown: ["video ingestion", "AI perception"] });
    expect(s.detail).toMatch(/are stopped/);
    expect(s.label).toBe("Not recording");
  });
});
