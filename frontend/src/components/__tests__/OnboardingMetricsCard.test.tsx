import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OnboardingMetricsCard } from "@/components/OnboardingMetricsCard";

const mocks = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ authFetch: mocks.fetch }) }));

afterEach(cleanup);
beforeEach(() => vi.resetAllMocks());

const metrics = {
  users_with_preferences: 12,
  goal_counts: { entrance: 7, review: 5 },
  place_counts: { home: 8, business: 4 },
  focus_counts: { daily: 10, setup: 2 },
  paused_count: 1,
  configured_count: 6,
  verified_count: 3,
  verified_rate: 0.5,
  abandoned_count: 2,
  synthetic_only_count: 1,
  median_seconds_to_first_useful: 420,
  verified_by_goal: { entrance: 3 },
};

describe("OnboardingMetricsCard", () => {
  it("renders the headline aggregates", async () => {
    mocks.fetch.mockResolvedValue({ ok: true, json: async () => metrics });
    render(<OnboardingMetricsCard />);

    expect(await screen.findByText("Verified rate")).toBeInTheDocument();
    expect(screen.getByText("50%")).toBeInTheDocument();
    expect(screen.getByText("7 min")).toBeInTheDocument();
    expect(screen.getByText("Abandoned (7d+)")).toBeInTheDocument();
  });

  it("shows a dash when there is no first-useful time yet", async () => {
    mocks.fetch.mockResolvedValue({ ok: true, json: async () => ({ ...metrics, median_seconds_to_first_useful: null, verified_count: 0, verified_rate: 0 }) });
    render(<OnboardingMetricsCard />);
    expect(await screen.findByText("—")).toBeInTheDocument();
    expect(screen.getByText("0%")).toBeInTheDocument();
  });

  it("surfaces a load error", async () => {
    mocks.fetch.mockResolvedValue({ ok: false });
    render(<OnboardingMetricsCard />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/Could not load/);
  });
});
