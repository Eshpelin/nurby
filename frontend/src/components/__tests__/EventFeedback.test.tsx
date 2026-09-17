import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EventFeedbackPanel } from "@/components/events/EventFeedback";

const mocks = vi.hoisted(() => ({ fetch: vi.fn(), user: { id: "user-1" } }));
vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ authFetch: mocks.fetch, user: mocks.user }),
}));

afterEach(cleanup);
beforeEach(() => vi.resetAllMocks());

const EVENT_ID = "e1";

function ok(body: unknown) {
  return { ok: true, status: 200, json: async () => body };
}

describe("EventFeedbackPanel", () => {
  it("rates useful in one tap and incorrect asks for an optional reason", async () => {
    const puts: unknown[] = [];
    let saved: unknown[] = [];
    mocks.fetch.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "PUT") {
        const body = JSON.parse(init.body as string);
        puts.push(body);
        saved = [{
          id: "fb1", event_id: EVENT_ID, user_id: "user-1",
          reviewer_display_name: "Me", ...body,
        }];
        return ok(saved[0]);
      }
      return ok(saved);
    });

    render(<EventFeedbackPanel eventId={EVENT_ID} />);

    fireEvent.click(await screen.findByRole("button", { name: /Incorrect/ }));
    await waitFor(() => expect(puts).toEqual([{ rating: "incorrect" }]));

    // The optional reason chips appear only after an incorrect rating...
    fireEvent.click(await screen.findByRole("button", { name: "Duplicate" }));
    await waitFor(() => expect(puts[1]).toEqual({ rating: "incorrect", reason: "duplicate" }));
  });

  it("keeps the reason chips hidden for useful ratings", async () => {
    let saved: unknown[] = [];
    mocks.fetch.mockImplementation(async (_url: string, init?: RequestInit) => {
      if (init?.method === "PUT") {
        const body = JSON.parse(init.body as string);
        saved = [{
          id: "fb1", event_id: EVENT_ID, user_id: "user-1",
          reviewer_display_name: "Me", ...body,
        }];
        return ok(saved[0]);
      }
      return ok(saved);
    });

    render(<EventFeedbackPanel eventId={EVENT_ID} />);
    fireEvent.click(await screen.findByRole("button", { name: /Useful/ }));
    await waitFor(() =>
      expect(screen.getByText(/yours saved/)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/What was wrong/)).not.toBeInTheDocument();
  });

  it("shows the review count and the household's reviewers", async () => {
    mocks.fetch.mockImplementation(async () =>
      ok([
        { id: "f1", event_id: EVENT_ID, user_id: "u2", reviewer_display_name: "Alice", rating: "useful", reason: null },
        { id: "f2", event_id: EVENT_ID, user_id: "u3", reviewer_display_name: "Bob", rating: "incorrect", reason: "timing" },
      ]),
    );

    render(<EventFeedbackPanel eventId={EVENT_ID} />);
    expect(await screen.findByText(/2 reviews/)).toBeInTheDocument();
    // The viewer has not rated yet, so there is nothing to withdraw.
    expect(screen.queryByRole("button", { name: "Withdraw" })).not.toBeInTheDocument();
  });
});
