import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ActivationSteps } from "@/components/ActivationSteps";
import type { ActivationView } from "@/lib/activation";

const mocks = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ authFetch: mocks.fetch }) }));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));

afterEach(cleanup);
beforeEach(() => vi.resetAllMocks());

function view(overrides: Partial<ActivationView>): ActivationView {
  return {
    goal: "entrance",
    rule_id: null,
    camera_id: null,
    draft_rule_id: null,
    steps: [
      { key: "configured", done: false, synthetic: false },
      { key: "tested", done: false, synthetic: false },
      { key: "confirmed", done: false, synthetic: false },
    ],
    verified: false,
    next_step: "configured",
    test_kind: null,
    seconds_to_first_useful: null,
    ...overrides,
  };
}

const list = (v: ActivationView | null) => ({ ok: true, json: async () => ({ milestones: v ? [v] : [] }) });

describe("ActivationSteps", () => {
  it("offers a disabled draft rule when nothing is scaffolded and never claims verified", async () => {
    mocks.fetch.mockResolvedValue(list(null));
    render(<ActivationSteps goal="entrance" cameraId={null} />);

    expect(await screen.findByRole("button", { name: /Create draft rule \(disabled\)/ })).toBeInTheDocument();
    expect(screen.queryByText("Verified")).not.toBeInTheDocument();
    expect(screen.getByText(/not activation/i)).toBeInTheDocument();
  });

  it("labels a synthetic test and still refuses to show verified", async () => {
    mocks.fetch.mockResolvedValue(list(view({
      rule_id: "r1",
      steps: [
        { key: "configured", done: true, synthetic: false },
        { key: "tested", done: true, synthetic: true },
        { key: "confirmed", done: false, synthetic: false },
      ],
      test_kind: "synthetic",
      next_step: "tested",
    })));
    render(<ActivationSteps goal="entrance" cameraId={null} />);

    expect(await screen.findByText("Synthetic test")).toBeInTheDocument();
    expect(screen.queryByText("Verified")).not.toBeInTheDocument();
    // Confirm control appears because tested is done, but success is not asserted.
    expect(screen.getByRole("button", { name: /I opened the clip/ })).toBeInTheDocument();
  });

  it("shows a verified badge only when the view says verified", async () => {
    mocks.fetch.mockResolvedValue(list(view({
      rule_id: "r1",
      steps: [
        { key: "configured", done: true, synthetic: false },
        { key: "tested", done: true, synthetic: false },
        { key: "confirmed", done: true, synthetic: false },
      ],
      verified: true,
      next_step: null,
      test_kind: "real",
      seconds_to_first_useful: 300,
    })));
    render(<ActivationSteps goal="entrance" cameraId={null} />);

    expect(await screen.findByText("Verified")).toBeInTheDocument();
    expect(screen.getByText(/in 5 min/)).toBeInTheDocument();
  });

  it("surfaces the server's reason when confirm is refused", async () => {
    mocks.fetch.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        return { ok: false, json: async () => ({ detail: "No delivered test event yet. Trigger the camera and wait for the alert" }) };
      }
      return list(view({
        rule_id: "r1",
        steps: [
          { key: "configured", done: true, synthetic: false },
          { key: "tested", done: true, synthetic: false },
          { key: "confirmed", done: false, synthetic: false },
        ],
      }));
    });
    render(<ActivationSteps goal="entrance" cameraId={null} />);

    fireEvent.click(await screen.findByRole("button", { name: /I opened the clip/ }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/No delivered test event yet/));
  });
});
