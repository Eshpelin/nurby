import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PersonalOnboardingCard } from "@/components/PersonalOnboardingCard";

const mocks = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ authFetch: mocks.fetch }) }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));

afterEach(cleanup);
beforeEach(() => vi.resetAllMocks());

function experience(body: unknown) {
  return { ok: true, json: async () => body };
}

const noop = () => {};

describe("PersonalOnboardingCard", () => {
  it("admin previews then saves a goal without any activation claim", async () => {
    let saved: unknown = null;
    mocks.fetch.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "PUT") {
        saved = JSON.parse(init.body as string);
        return experience({ preferences: saved, audience: "administrator" });
      }
      return experience({ preferences: null, audience: "administrator" });
    });

    render(<PersonalOnboardingCard cameraCount={0} camerasLoading={false} onSetup={noop} />);

    // The picker opens for a fresh admin.
    fireEvent.click(await screen.findByRole("button", { name: "Small business" }));
    fireEvent.click(screen.getByRole("button", { name: /Review activity after closing/ }));
    fireEvent.click(screen.getByRole("button", { name: "Preview recommendation" }));

    // The preview promises no activation and no permission change.
    expect(await screen.findByText(/does not create rules/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Use this setup" }));

    await waitFor(() => expect(saved).toEqual({ version: 1, place: "business", goal: "after_hours", focus: "daily" }));
    // Saved view is explicit that monitoring is not yet verified.
    expect(await screen.findByText(/monitoring is not verified here/i)).toBeInTheDocument();
  });

  it("shows a retryable error when saving fails and keeps setup unchanged", async () => {
    let attempts = 0;
    mocks.fetch.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "PUT") { attempts += 1; return { ok: false }; }
      return experience({ preferences: null, audience: "administrator" });
    });

    render(<PersonalOnboardingCard cameraCount={2} camerasLoading={false} onSetup={noop} />);

    fireEvent.click(await screen.findByRole("button", { name: "Preview recommendation" }));
    fireEvent.click(await screen.findByRole("button", { name: "Use this setup" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/Could not save/i);
    // Still in the editor, so the save can be retried.
    expect(screen.getByRole("button", { name: "Use this setup" })).toBeInTheDocument();
    expect(attempts).toBe(1);
  });

  it("gives an invited viewer a review-only path with no installation controls", async () => {
    mocks.fetch.mockResolvedValue(experience({ preferences: { version: 1, place: null, goal: "review", focus: "daily" }, audience: "viewer" }));

    render(<PersonalOnboardingCard cameraCount={1} camerasLoading={false} onSetup={noop} />);

    expect(await screen.findByRole("link", { name: /Review available activity/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Set up a camera/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Preview recommendation/ })).not.toBeInTheDocument();
  });

  it("keeps a guardian on their dependant portal", async () => {
    mocks.fetch.mockResolvedValue(experience({ preferences: null, audience: "guardian" }));

    render(<PersonalOnboardingCard cameraCount={0} camerasLoading={false} onSetup={noop} />);

    expect(await screen.findByRole("link", { name: /Open Guardian/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Set up a camera/ })).not.toBeInTheDocument();
  });

  it("surfaces a retry when preferences cannot be loaded", async () => {
    mocks.fetch.mockResolvedValue({ ok: false });

    render(<PersonalOnboardingCard cameraCount={0} camerasLoading={false} onSetup={noop} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/current setup is unchanged/i);
    expect(screen.getByRole("button", { name: /Retry preferences/ })).toBeInTheDocument();
  });
});
