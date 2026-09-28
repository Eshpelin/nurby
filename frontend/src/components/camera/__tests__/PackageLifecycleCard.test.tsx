import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { PackageLifecycleCard } from "../PackageLifecycleCard";

describe("PackageLifecycleCard", () => {
  it("adds the auth token to direct evidence links", async () => {
    const authFetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      items: [{
        id: "life-1",
        state: "delivered",
        started_at: "2026-09-28T10:00:00Z",
        last_present_at: "2026-09-28T10:01:00Z",
        gone_at: null,
        removal_kind: null,
        absent_checks: 0,
        last_observation_id: "obs-1",
        evidence: null,
        updated_at: "2026-09-28T10:01:00Z",
      }],
    })));

    render(<PackageLifecycleCard cameraId="cam-1" token="secret token" authFetch={authFetch} />);
    expect(await screen.findByRole("link", { name: "Last presence frame" })).toHaveAttribute(
      "href",
      "/api/observations/obs-1/thumbnail?token=secret%20token",
    );
  });

  it("shows before and after evidence for an unexplained disappearance", async () => {
    const authFetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      items: [{
        id: "life-1",
        state: "gone",
        started_at: "2026-09-28T10:00:00Z",
        last_present_at: "2026-09-28T10:01:00Z",
        gone_at: "2026-09-28T10:05:00Z",
        removal_kind: "removed_unobserved",
        absent_checks: 2,
        last_observation_id: "obs-after",
        evidence: { last_present_observation_id: "obs-before" },
        updated_at: "2026-09-28T10:05:00Z",
      }],
    })));

    render(<PackageLifecycleCard cameraId="cam-1" token="token" authFetch={authFetch} />);
    expect(await screen.findByRole("link", { name: "Before disappearance" })).toHaveAttribute(
      "href",
      "/api/observations/obs-before/thumbnail?token=token",
    );
    expect(screen.getByRole("link", { name: "Removal evidence frame" })).toHaveAttribute(
      "href",
      "/api/observations/obs-after/thumbnail?token=token",
    );
  });
});
