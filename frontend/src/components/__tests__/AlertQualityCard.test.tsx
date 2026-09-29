import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AlertQualityCard } from "@/components/AlertQualityCard";

const mocks = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ authFetch: mocks.fetch, user: { locale: "en", role: "admin" } }),
}));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));

afterEach(cleanup);
beforeEach(() => vi.resetAllMocks());

describe("AlertQualityCard (#199)", () => {
  it("shows explicit nuisance and feedback denominators", async () => {
    mocks.fetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        window_hours: 168,
        events_fired: 20,
        events_reviewed: 10,
        response_rate: 0.5,
        nuisance_alerts: 3,
        nuisance_rate_reviewed: 0.3,
        nuisance_rate_fired: 0.15,
        delivered_alerts: 10,
        opened_alerts: 4,
        open_rate_delivered: 0.4,
        clip_opened_alerts: 2,
        clip_open_rate_delivered: 0.2,
        delivery_by_channel: [
          { channel: "in_app", delivered_alerts: 10, opened_alerts: 4, clip_opened_alerts: 2 },
          { channel: "push", delivered_alerts: 5, opened_alerts: 0, clip_opened_alerts: 0 },
        ],
        nuisance_by_camera_day: [{ camera_id: "camera-1", day: "2026-09-29", reviewed: 2, nuisance: 1, nuisance_rate_reviewed: 0.5 }],
      }),
    });

    render(<AlertQualityCard />);

    expect(await screen.findByText("Alert quality")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("30%")).toBeInTheDocument();
    expect(screen.getByText(/15% of all fired alerts/)).toBeInTheDocument();
    expect(screen.getByText(/4\/10 \(40%\)/)).toBeInTheDocument();
    expect(screen.getByText(/2\/10 \(20%\)/)).toBeInTheDocument();
    expect(screen.getByText(/in_app: 10/)).toBeInTheDocument();
    expect(screen.getByText(/Nuisance by camera-day/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Review alerts" })).toHaveAttribute("href", "/events");
  });
});
