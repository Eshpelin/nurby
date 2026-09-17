import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import CameraAccessPage from "./page";

const mocks = vi.hoisted(() => ({ fetch: vi.fn(), success: vi.fn(), error: vi.fn() }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: { role: "admin" }, authFetch: mocks.fetch }) }));
vi.mock("@/lib/feedback", () => ({ useToast: () => ({ success: mocks.success, error: mocks.error }) }));

afterEach(cleanup);
beforeEach(() => vi.resetAllMocks());

describe("camera access controls", () => {
  it("revoking the final selected camera shows no access", async () => {
    const viewer = { id: "viewer", display_name: "Alex", email: "alex@example.com", role: "viewer", is_active: true, camera_access_mode: "selected" };
    const camera = { id: "door", name: "Front door", location_label: null };
    let granted = true;
    mocks.fetch.mockImplementation(async (url: string, init?: RequestInit) => {
      if (init?.method === "DELETE") { granted = false; return { ok: true }; }
      const data = url === "/api/users" ? [viewer] : url === "/api/cameras" ? [camera]
        : url.endsWith("/cameras") ? (granted ? [camera] : []) : viewer;
      return { ok: true, json: async () => data };
    });
    render(<CameraAccessPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Alex/ }));
    const toggle = await screen.findByRole("checkbox", { name: "Front door" });
    expect(toggle).toBeChecked();
    fireEvent.click(toggle);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Cannot see any cameras."));
    expect(screen.getByLabelText("Camera access mode")).toHaveValue("selected");
    expect(mocks.fetch).toHaveBeenCalledWith("/api/users/viewer/cameras/door", { method: "DELETE" });
  });

  it("does not present a failed permission read as editable no-access state", async () => {
    const viewer = { id: "viewer", display_name: "Alex", role: "viewer", is_active: true };
    mocks.fetch.mockImplementation(async (url: string) => ({
      ok: url === "/api/users" || url === "/api/cameras",
      json: async () => url === "/api/users" ? [viewer] : [],
    }));
    render(<CameraAccessPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Alex/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load camera access");
    expect(screen.queryByLabelText("Camera access mode")).not.toBeInTheDocument();
  });
});
