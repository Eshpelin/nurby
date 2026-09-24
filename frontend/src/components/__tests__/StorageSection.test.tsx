import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { StorageSection } from "@/components/camera/settings/StorageSection";

const mocks = vi.hoisted(() => ({ fetch: vi.fn(), role: "admin" }));
vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ authFetch: mocks.fetch, user: { role: mocks.role, id: "u1" } }),
}));

afterEach(cleanup);
beforeEach(() => vi.resetAllMocks());

const ok = (body: unknown) => ({ ok: true, json: async () => body });

function router(profiles: unknown[]) {
  return (url: string) => {
    if (url.includes("/api/storage-profiles")) return Promise.resolve(ok(profiles));
    if (url.includes("/api/system/storage"))
      return Promise.resolve(
        ok({
          locations: [{ key: "recordings", path: "/data/recordings", source: "default", exists: true, writable: true, free_bytes: 1 }],
          docker: false,
          low_space: false,
          warnings: [],
        })
      );
    return Promise.resolve(ok({}));
  };
}

const noop = () => {};
const profile = { id: "p1", name: "NAS", kind: "ftp", root: "/nurby", enabled: true };

describe("StorageSection stale assignment (#280)", () => {
  afterEach(() => {
    mocks.role = "admin";
  });

  it("clears a deleted profile and explains the fallback", async () => {
    mocks.fetch.mockImplementation(router([profile]));
    const setStorageProfileId = vi.fn();
    render(<StorageSection storageProfileId="deleted-id" setStorageProfileId={setStorageProfileId} />);
    await waitFor(() => expect(setStorageProfileId).toHaveBeenCalledWith(null));
    expect(await screen.findByText(/storage location was deleted/i)).toBeInTheDocument();
    // The dropdown falls back to the default option.
    expect((screen.getByRole("combobox") as HTMLSelectElement).value).toBe("");
  });

  it("keeps a still-existing profile assignment untouched", async () => {
    mocks.fetch.mockImplementation(router([profile]));
    const setStorageProfileId = vi.fn();
    render(<StorageSection storageProfileId="p1" setStorageProfileId={setStorageProfileId} />);
    await screen.findByText(/on FTP/i);
    await waitFor(() => expect(setStorageProfileId).not.toHaveBeenCalled());
  });

  it("leaves page state untouched for non-admins (endpoint 403s)", async () => {
    mocks.role = "viewer";
    mocks.fetch.mockImplementation(() => ({ ok: false, json: async () => ({}) }));
    const setStorageProfileId = vi.fn();
    render(<StorageSection storageProfileId="p1" setStorageProfileId={setStorageProfileId} />);
    await waitFor(() => expect(mocks.fetch).toHaveBeenCalled());
    expect(setStorageProfileId).not.toHaveBeenCalled();
  });
});
