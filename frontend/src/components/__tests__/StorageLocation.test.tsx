import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  StorageLocationCard,
  StorageLocationForm,
  StorageLowSpaceBanner,
  StorageOverviewBlock,
} from "@/components/settings/StorageLocation";

const mocks = vi.hoisted(() => ({ fetch: vi.fn(), role: "admin" }));
vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ authFetch: mocks.fetch, user: { role: mocks.role, id: "u1" } }),
}));
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));

afterEach(cleanup);
beforeEach(() => vi.resetAllMocks());

const ok = (body: unknown) => ({ ok: true, json: async () => body });

const overview = (over: Record<string, unknown> = {}) => ({
  locations: [
    { key: "recordings", path: "/data/recordings", source: "default", exists: true, writable: true, free_bytes: 2 * 1024 ** 3, total_bytes: null },
    { key: "thumbnails", path: "/data/thumbnails", source: "default", exists: true, writable: true, free_bytes: null, total_bytes: null },
    { key: "audio", path: "/data/audio", source: "default", exists: true, writable: true, free_bytes: null, total_bytes: null },
  ],
  docker: false,
  low_space: true,
  warnings: ["Only 2.0 GB free at /data/recordings. With retention on, old media will be deleted as space runs out."],
  ...over,
});

function fetchRouter(overview: unknown | null) {
  return (url: string) => {
    if (url.includes("/api/system/storage")) {
      return overview === null ? { ok: false, json: async () => ({}) } : Promise.resolve(ok(overview));
    }
    if (url.includes("/api/storage-profiles")) {
      return Promise.resolve(ok([]));
    }
    return Promise.resolve(ok({}));
  };
}

describe("StorageLowSpaceBanner (#274)", () => {
  it("renders the low-space warning with a link to Settings for admins", async () => {
    mocks.fetch.mockImplementation(fetchRouter(overview()));
    render(<StorageLowSpaceBanner />);
    expect(await screen.findByText(/Low disk space/i)).toBeInTheDocument();
    expect(screen.getByText(/Only 2.0 GB free/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Review storage" })).toHaveAttribute("href", "/settings#storage");
  });

  it("renders nothing when space is healthy", () => {
    mocks.fetch.mockImplementation(fetchRouter(overview({ low_space: false, warnings: [] })));
    const { container } = render(<StorageLowSpaceBanner />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing for non-admins (admin-only endpoint)", () => {
    mocks.role = "viewer";
    mocks.fetch.mockImplementation(fetchRouter(overview()));
    const { container } = render(<StorageLowSpaceBanner />);
    expect(container).toBeEmptyDOMElement();
    expect(mocks.fetch).not.toHaveBeenCalled();
    mocks.role = "admin";
  });
});

describe("StorageOverviewBlock (#274)", () => {
  it("lists every media root and surfaces the warnings", async () => {
    mocks.fetch.mockImplementation(fetchRouter(overview()));
    render(<StorageOverviewBlock />);
    expect(await screen.findByText("Recordings")).toBeInTheDocument();
    expect(screen.getByText("Thumbnails")).toBeInTheDocument();
    expect(screen.getByText("Audio")).toBeInTheDocument();
    expect(screen.getByText(/Only 2.0 GB free at/)).toBeInTheDocument();
    expect(screen.getAllByText(/\/data\/recordings/).length).toBeGreaterThan(0);
  });

  it("handles a failed overview fetch without crashing", async () => {
    mocks.fetch.mockImplementation(fetchRouter(null));
    render(<StorageOverviewBlock />);
    expect(await screen.findByText("Loading locations…")).toBeInTheDocument();
  });
});


describe("StorageLocationForm consequence warning (#278)", () => {
  it("warns that changed locations affect new recordings only", async () => {
    mocks.fetch.mockImplementation(fetchRouter(overview()));
    render(<StorageLocationForm />);
    const input = await screen.findByLabelText("Where should recordings be stored?");
    expect(screen.queryByText(/won't play until moved/i)).not.toBeInTheDocument();
    fireEvent.change(input, { target: { value: "/mnt/elsewhere" } });
    expect(screen.getByText(/won't play until moved/i)).toBeInTheDocument();
    expect(screen.getByText(/Migration notes/i)).toHaveAttribute(
      "href",
      "https://github.com/Eshpelin/nurby/blob/main/docs/operations/storage-location.md"
    );
  });

  it("stays quiet while the current location is unchanged", async () => {
    mocks.fetch.mockImplementation(fetchRouter(overview()));
    render(<StorageLocationForm />);
    await screen.findByLabelText("Where should recordings be stored?");
    // Prefill happened; no change -> no warning.
    expect(screen.queryByText(/won't play until moved/i)).not.toBeInTheDocument();
  });
});


describe("StorageLocationCard gating (#279)", () => {
  it("shows an admin note instead of the form for non-admins", () => {
    mocks.role = "viewer";
    mocks.fetch.mockImplementation(fetchRouter(overview()));
    render(<StorageLocationCard />);
    expect(screen.getByText(/Only admins can change the storage location/i)).toBeInTheDocument();
    expect(screen.queryByLabelText("Where should recordings be stored?")).not.toBeInTheDocument();
    mocks.role = "admin";
  });

  it("renders the full block for admins", async () => {
    mocks.fetch.mockImplementation(fetchRouter(overview()));
    render(<StorageLocationCard />);
    expect(await screen.findByText("Recordings location")).toBeInTheDocument();
    expect(await screen.findByText("Recordings")).toBeInTheDocument();
  });

  it("shows uploaded usage for FTP locations", async () => {
    mocks.fetch.mockImplementation((url: string) => {
      if (url.includes("/api/system/storage")) return Promise.resolve(ok(overview()));
      if (url.includes("/api/storage-profiles")) {
        return Promise.resolve(ok([{ id: "ftp-1", name: "NAS", kind: "ftp", stats: { uploaded_bytes: 2 * 1024 ** 3 } }]));
      }
      return Promise.resolve(ok({}));
    });
    render(<StorageOverviewBlock />);
    expect(await screen.findByText("2.0 GB stored")).toBeInTheDocument();
    expect(screen.getByText(/FTP capacity is not queried/i)).toBeInTheDocument();
  });
});
