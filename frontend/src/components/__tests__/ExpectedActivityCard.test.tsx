import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ExpectedActivityCard } from "@/components/ExpectedActivityCard";

const mocks = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ authFetch: mocks.fetch }) }));

afterEach(cleanup);
beforeEach(() => vi.resetAllMocks());

const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body });

describe("ExpectedActivityCard", () => {
  it("uses stable person and camera ids when creating an expectation", async () => {
    let createBody: Record<string, unknown> | null = null;
    mocks.fetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/expected-activity" && init?.method === "POST") {
        createBody = JSON.parse(String(init.body));
        return Promise.resolve(ok({ id: "e-1", ...createBody }));
      }
      if (url === "/api/expected-activity") return Promise.resolve(ok([]));
      if (url === "/api/persons") return Promise.resolve(ok([{ id: "p-1", display_name: "Alex", nickname: "Lex" }]));
      if (url === "/api/cameras") return Promise.resolve(ok([{ id: "c-1", name: "Front Door" }]));
      return Promise.resolve({ ok: false, status: 404 });
    });

    render(<ExpectedActivityCard />);
    fireEvent.change(await screen.findByPlaceholderText(/Expectation name/), { target: { value: "Alex arrives" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Expected person" }), { target: { value: "p-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Front Door" }));
    fireEvent.click(screen.getByRole("button", { name: "Add expectation" }));

    await waitFor(() => expect(createBody).not.toBeNull());
    expect(createBody).toMatchObject({
      name: "Alex arrives",
      subject_kind: "person",
      subject_person_id: "p-1",
      camera_ids: ["c-1"],
    });
    expect(screen.getByText(/Choose a person by identity/)).toBeInTheDocument();
  });
});
