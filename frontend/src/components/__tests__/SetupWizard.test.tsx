import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SetupWizard } from "@/components/SetupWizard";

const mocks = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ authFetch: mocks.fetch }) }));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));

afterEach(cleanup);
beforeEach(() => vi.resetAllMocks());

const ok = (body: unknown) => ({ ok: true, json: async () => body });
const steps = (c: boolean, t: boolean, f: boolean, synthetic = false) => [
  { key: "configured", done: c, synthetic: false },
  { key: "tested", done: t, synthetic },
  { key: "confirmed", done: f, synthetic: false },
];

function router(experience: unknown, activation: unknown | (() => unknown), onPost?: (url: string, init: RequestInit) => unknown) {
  return (url: string, init?: RequestInit) => {
    if (init?.method === "POST" || init?.method === "PUT") {
      return Promise.resolve(ok(onPost?.(url, init) ?? {}));
    }
    if (url.includes("/me/experience")) return Promise.resolve(ok(experience));
    // Rebuild activation each call so a state refresh after an action is a
    // fresh object (a shared reference would be skipped by setState).
    if (url.includes("/me/activation")) return Promise.resolve(ok(typeof activation === "function" ? (activation as () => unknown)() : activation));
    if (url.includes("/me/daily")) return Promise.resolve(ok({ audience: "administrator", paused: false, place_label: null, priorities: [] }));
    return Promise.resolve(ok({}));
  };
}

const noop = () => {};
const props = { cameraCount: 1, camerasLoading: false, onSetupCamera: noop, onClose: noop, onChanged: noop };

describe("SetupWizard", () => {
  it("starts at the goal step with a 4-step progress for a fresh admin", async () => {
    mocks.fetch.mockImplementation(router({ preferences: null, audience: "administrator" }, { milestones: [] }));
    render(<SetupWizard {...props} />);
    expect(await screen.findByText(/What should Nurby watch for first/i)).toBeInTheDocument();
    expect(screen.getByText(/Step 1 of 4/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue" })).toBeInTheDocument();
  });

  it("resumes at the rule step and offers to enable an existing draft", async () => {
    mocks.fetch.mockImplementation(router(
      { preferences: { version: 1, place: "home", goal: "entrance", focus: "daily" }, audience: "administrator" },
      { milestones: [{ goal: "entrance", steps: steps(false, false, false), verified: false, next_step: "configured", test_kind: null, seconds_to_first_useful: null, rule_id: "r1", camera_id: null, draft_rule_id: "d1" }] },
    ));
    render(<SetupWizard {...props} />);
    expect(await screen.findByText("Set up the rule")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open the draft rule/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /I've enabled it/ })).toBeInTheDocument();
    expect(screen.getByText(/Step 2 of 4/)).toBeInTheDocument();
  });

  it("waits for a real alert on the test step", async () => {
    mocks.fetch.mockImplementation(router(
      { preferences: { version: 1, place: "home", goal: "entrance", focus: "daily" }, audience: "administrator" },
      { milestones: [{ goal: "entrance", steps: steps(true, false, false), verified: false, next_step: "tested", test_kind: null, seconds_to_first_useful: null, rule_id: "r1", camera_id: null, draft_rule_id: "d1" }] },
    ));
    render(<SetupWizard {...props} />);
    expect(await screen.findByText("Trigger a real event")).toBeInTheDocument();
    expect(screen.getByText(/Waiting for the alert/)).toBeInTheDocument();
    // Cannot advance to confirm until a real alert lands.
    expect(screen.getByRole("button", { name: /Next: confirm the clip/ })).toBeDisabled();
  });

  it("confirms the clip and lands on the verified done screen", async () => {
    let confirmed = false;
    const milestone = (c: boolean) => ({ goal: "entrance", steps: steps(true, true, c), verified: c, next_step: c ? null : "confirmed", test_kind: "real", seconds_to_first_useful: c ? 240 : null, rule_id: "r1", camera_id: null, draft_rule_id: "d1" });
    mocks.fetch.mockImplementation(router(
      { preferences: { version: 1, place: "home", goal: "entrance", focus: "daily" }, audience: "administrator" },
      () => ({ milestones: [milestone(confirmed)] }),
      (url) => { if (url.includes("/confirm")) confirmed = true; return {}; },
    ));
    render(<SetupWizard {...props} />);
    fireEvent.click(await screen.findByRole("button", { name: /I opened the clip/ }));
    expect(await screen.findByText(/You're verified/)).toBeInTheDocument();
    expect(screen.getByText(/in 4 min/)).toBeInTheDocument();
  });

  it("skips the rule step to test without configuring it on the server", async () => {
    const posts: string[] = [];
    mocks.fetch.mockImplementation(router(
      { preferences: { version: 1, place: "home", goal: "entrance", focus: "daily" }, audience: "administrator" },
      { milestones: [{ goal: "entrance", steps: steps(false, false, false), verified: false, next_step: "configured", test_kind: null, seconds_to_first_useful: null, rule_id: "r1", camera_id: null, draft_rule_id: "d1" }] },
      (url) => { posts.push(url); return {}; },
    ));
    render(<SetupWizard {...props} />);
    fireEvent.click(await screen.findByRole("button", { name: /Skip this step for now/ }));
    // Advances to the test step by navigation only.
    expect(await screen.findByText("Trigger a real event")).toBeInTheDocument();
    // No activation endpoint was hit, so nothing was faked as complete.
    expect(posts.some((u) => u.includes("/configure"))).toBe(false);
  });

  it("closes the wizard when skipping the goal step", async () => {
    const onClose = vi.fn();
    mocks.fetch.mockImplementation(router({ preferences: null, audience: "administrator" }, { milestones: [] }));
    render(<SetupWizard {...props} onClose={onClose} />);
    fireEvent.click(await screen.findByRole("button", { name: /Do this later/ }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("shows a dismissible coach-mark pointing at the camera setup control", async () => {
    mocks.fetch.mockImplementation(router(
      { preferences: { version: 1, place: "home", goal: "entrance", focus: "daily" }, audience: "administrator" },
      { milestones: [{ goal: "entrance", steps: steps(false, false, false), verified: false, next_step: "configured", test_kind: null, seconds_to_first_useful: null, rule_id: "r1", camera_id: null, draft_rule_id: null }] },
    ));
    render(<SetupWizard {...props} cameraCount={0} />);
    expect(await screen.findByRole("button", { name: /Set up a camera/ })).toBeInTheDocument();
    expect(await screen.findByText(/Start here. Connect a camera/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Dismiss tip/ }));
    await waitFor(() => expect(screen.queryByText(/Start here. Connect a camera/)).not.toBeInTheDocument());
  });

  it("takes an explore goal straight to a done screen", async () => {
    mocks.fetch.mockImplementation(router(
      { preferences: { version: 1, place: null, goal: "explore", focus: "daily" }, audience: "administrator" },
      { milestones: [] },
    ));
    render(<SetupWizard {...props} />);
    expect(await screen.findByText(/You're all set/)).toBeInTheDocument();
    // No detection stepper for a no-rule goal.
    expect(screen.queryByText(/Step 1 of 4/)).not.toBeInTheDocument();
  });
});
