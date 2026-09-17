import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DailyPriorities } from "@/components/DailyPriorities";

const mocks = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ authFetch: mocks.fetch }) }));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));

afterEach(cleanup);
beforeEach(() => vi.resetAllMocks());

const workflow = (over: object) => ({
  ok: true,
  json: async () => ({ audience: "administrator", paused: false, place_label: "Front shop", priorities: [], ...over }),
});

describe("DailyPriorities", () => {
  it("renders priorities with a blocked reason and the place name", async () => {
    mocks.fetch.mockResolvedValue(workflow({
      priorities: [
        { key: "verify-activation", title: "Finish verifying your first alert", detail: "…", href: "/", blocked_reason: "Add a way to be notified" },
      ],
    }));
    render(<DailyPriorities paused={false} onTogglePause={() => {}} />);

    expect(await screen.findByText(/Front shop/)).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: /Finish verifying/ })).toBeInTheDocument();
    expect(screen.getByText("Add a way to be notified")).toBeInTheDocument();
  });

  it("shows a pause control that calls back, and a resume label when paused", async () => {
    mocks.fetch.mockResolvedValue(workflow({ paused: true, priorities: [{ key: "resume", title: "Daily guidance paused", detail: "Your rules keep running.", href: "/", blocked_reason: null }] }));
    const onToggle = vi.fn();
    render(<DailyPriorities paused onTogglePause={onToggle} />);

    const btn = await screen.findByRole("button", { name: /Resume daily guidance/ });
    fireEvent.click(btn);
    expect(onToggle).toHaveBeenCalledOnce();
    expect(screen.getByText(/rules keep running/)).toBeInTheDocument();
  });

  it("surfaces a load error", async () => {
    mocks.fetch.mockResolvedValue({ ok: false });
    render(<DailyPriorities paused={false} onTogglePause={() => {}} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/Could not load/);
  });
});
