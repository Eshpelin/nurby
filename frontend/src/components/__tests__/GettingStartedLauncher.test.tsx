import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GettingStartedLauncher } from "@/components/GettingStartedLauncher";

const mocks = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ authFetch: mocks.fetch }) }));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));

afterEach(cleanup);
beforeEach(() => vi.resetAllMocks());

const ok = (body: unknown) => ({ ok: true, json: async () => body });

// Route fetches by URL so the launcher and the card it embeds each get
// sensible data.
function router(opts: { experience: unknown; activation: unknown }) {
  return (url: string) => {
    if (url.includes("/me/experience")) return Promise.resolve(ok(opts.experience));
    if (url.includes("/me/activation")) return Promise.resolve(ok(opts.activation));
    if (url.includes("/me/daily")) return Promise.resolve(ok({ audience: "administrator", paused: false, place_label: null, priorities: [] }));
    return Promise.resolve(ok({}));
  };
}

const steps = (configured: boolean, tested: boolean, confirmed: boolean) => [
  { key: "configured", done: configured, synthetic: false },
  { key: "tested", done: tested, synthetic: false },
  { key: "confirmed", done: confirmed, synthetic: false },
];

describe("GettingStartedLauncher", () => {
  it("renders nothing for non-admins", async () => {
    mocks.fetch.mockImplementation(router({ experience: { preferences: null, audience: "viewer" }, activation: { milestones: [] } }));
    const { container } = render(<GettingStartedLauncher isAdmin={false} cameraCount={1} camerasLoading={false} onSetup={() => {}} />);
    // Never shows a launcher; give the effect a tick to prove it stays empty.
    await waitFor(() => expect(mocks.fetch).not.toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("prompts an admin with no preferences to set up", async () => {
    mocks.fetch.mockImplementation(router({ experience: { preferences: null, audience: "administrator" }, activation: { milestones: [] } }));
    render(<GettingStartedLauncher isAdmin cameraCount={0} camerasLoading={false} onSetup={() => {}} />);
    expect(await screen.findByRole("button", { name: /Set up Nurby/ })).toBeInTheDocument();
  });

  it("shows progress while activation is incomplete", async () => {
    mocks.fetch.mockImplementation(router({
      experience: { preferences: { version: 1, place: "home", goal: "entrance", focus: "daily" }, audience: "administrator" },
      activation: { milestones: [{ goal: "entrance", steps: steps(true, false, false), verified: false, next_step: "tested", test_kind: null, seconds_to_first_useful: null, rule_id: "r", camera_id: null, draft_rule_id: null }] },
    }));
    render(<GettingStartedLauncher isAdmin cameraCount={1} camerasLoading={false} onSetup={() => {}} />);
    expect(await screen.findByText("Getting started")).toBeInTheDocument();
    expect(await screen.findByText("1/3")).toBeInTheDocument();
  });

  it("retires to a settled state once verified", async () => {
    mocks.fetch.mockImplementation(router({
      experience: { preferences: { version: 1, place: "home", goal: "entrance", focus: "daily" }, audience: "administrator" },
      activation: { milestones: [{ goal: "entrance", steps: steps(true, true, true), verified: true, next_step: null, test_kind: "real", seconds_to_first_useful: 300, rule_id: "r", camera_id: null, draft_rule_id: null }] },
    }));
    render(<GettingStartedLauncher isAdmin cameraCount={1} camerasLoading={false} onSetup={() => {}} />);
    expect(await screen.findByRole("button", { name: /Nurby set up/ })).toBeInTheDocument();
    expect(screen.queryByText(/\d\/3/)).not.toBeInTheDocument();
  });

  it("opens the setup content in a popover on click", async () => {
    mocks.fetch.mockImplementation(router({ experience: { preferences: null, audience: "administrator" }, activation: { milestones: [] } }));
    render(<GettingStartedLauncher isAdmin cameraCount={0} camerasLoading={false} onSetup={() => {}} />);
    fireEvent.click(await screen.findByRole("button", { name: /Set up Nurby/ }));
    // The embedded card's first-run picker appears inside the popover.
    expect(await screen.findByText(/What would you like help with first/i)).toBeInTheDocument();
  });
});
