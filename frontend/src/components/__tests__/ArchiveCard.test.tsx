import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ArchiveCard } from "@/components/settings/ArchiveCard";

const mocks = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ authFetch: mocks.fetch, user: { role: "admin", id: "u1" } }),
}));

afterEach(cleanup);
beforeEach(() => vi.resetAllMocks());

const ok = (body: unknown) => ({ ok: true, json: async () => body });

const bucket = {
  id: "s3-1",
  name: "Cold archive",
  kind: "s3",
  root: "/nurby",
  enabled: true,
  config: { bucket: "cams" },
};
const cameras = [
  { id: "c1", name: "Front door", retention_mode: "time", retention_days: 30, retention_gb: 50 },
  { id: "c2", name: "Garage", retention_mode: "none", retention_days: 30, retention_gb: 50 },
];

function archive(over: Record<string, unknown> = {}) {
  return {
    profile_id: null,
    profile_name: null,
    kind: null,
    storage_class: null,
    retention_days: 0,
    active: false,
    broken: false,
    stats: { pending: 0, failed: 0, uploaded: 0, uploaded_bytes: 0 },
    cameras,
    ...over,
  };
}

describe("ArchiveCard (#270)", () => {
  it("offers only remote locations as the destination", async () => {
    mocks.fetch.mockImplementation((url: string) =>
      Promise.resolve(
        url.includes("/api/storage/archive")
          ? ok(archive())
          : ok([bucket, { id: "l1", name: "USB", kind: "local", root: "/mnt/usb", enabled: true }]),
      ),
    );
    render(<ArchiveCard />);
    const select = (await screen.findByLabelText("Archive destination")) as HTMLSelectElement;
    const labels = Array.from(select.options).map((o) => o.textContent);
    expect(labels).toContain("Cold archive (s3://cams/nurby)");
    expect(labels.some((l) => l?.includes("USB"))).toBe(false);
  });

  it("saves a destination and lifetime, then explains the flow", async () => {
    let saved: Record<string, unknown> | null = null;
    mocks.fetch.mockImplementation((url: string, init?: RequestInit) => {
      if (url.includes("/api/storage/archive") && init?.method === "PUT") {
        saved = JSON.parse(String(init.body));
        return Promise.resolve(ok({}));
      }
      if (url.includes("/api/storage/archive")) {
        return Promise.resolve(
          ok(
            saved
              ? archive({
                  profile_id: "s3-1",
                  profile_name: "Cold archive",
                  kind: "s3",
                  storage_class: "GLACIER_IR",
                  retention_days: 365,
                  active: true,
                  stats: { pending: 2, failed: 0, uploaded: 10, uploaded_bytes: 5 * 1024 ** 3 },
                })
              : archive(),
          ),
        );
      }
      return Promise.resolve(ok([bucket]));
    });
    render(<ArchiveCard />);
    fireEvent.change(await screen.findByLabelText("Archive destination"), { target: { value: "s3-1" } });
    fireEvent.change(screen.getByLabelText("Keep in the archive"), { target: { value: "365" } });
    fireEvent.click(screen.getByRole("button", { name: /Archive to Cold archive/ }));

    await waitFor(() => expect(saved).toEqual({ profile_id: "s3-1", retention_days: 365 }));
    expect(await screen.findByText(/deleted after 1 year/)).toBeInTheDocument();
    expect(screen.getByText(/10 archived \(5.0 GB\) · 2 moving now/)).toBeInTheDocument();
    // A camera that keeps everything locally never archives; say which.
    expect(screen.getByText(/nothing from it is archived/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Garage" })).toHaveAttribute("href", "/cameras/c2");
  });

  it("warns when the saved destination stopped working", async () => {
    mocks.fetch.mockImplementation((url: string) =>
      Promise.resolve(url.includes("/api/storage/archive") ? ok(archive({ broken: true })) : ok([])),
    );
    render(<ArchiveCard />);
    expect(await screen.findByText(/being deleted instead of archived/)).toBeInTheDocument();
  });
});
