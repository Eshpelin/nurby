import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RemoteAccessCard } from "@/components/RemoteAccessCard";

const mocks = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ authFetch: mocks.fetch, user: { role: "admin", id: "u1", locale: "en" } }),
}));

afterEach(cleanup);
beforeEach(() => vi.resetAllMocks());

const ok = (body: unknown) => ({ ok: true, json: async () => body });

const unconfigured = {
  configured: false,
  domain: null,
  scheme: null,
  public_base_url: null,
  connectivity: null,
  probe: null,
};

function configuredState(over: Record<string, unknown> = {}) {
  return {
    configured: true,
    domain: "camera.example.com",
    scheme: "https",
    public_base_url: "https://camera.example.com",
    connectivity: {
      public_ip: "203.0.113.7",
      domain_addresses: ["203.0.113.7"],
      dns_matches_public_ip: true,
      tls_ok: true,
      tls_detail: "valid until tomorrow",
      health_ok: true,
      health_detail: "HTTP 200",
      ingress_caddy: true,
    },
    probe: null,
    ...over,
  };
}

describe("RemoteAccessCard (#183)", () => {
  it("offers the domain form when nothing is configured", async () => {
    mocks.fetch.mockResolvedValue(ok(unconfigured));
    render(<RemoteAccessCard />);
    fireEvent.click(await screen.findByText("Remote access"));
    const input = await screen.findByLabelText("Your domain");
    fireEvent.change(input, { target: { value: "camera.example.com" } });
    fireEvent.click(screen.getByText("Use this domain"));
    await waitFor(() => expect(mocks.fetch).toHaveBeenCalledWith(
      "/api/system/remote-access/domain",
      expect.objectContaining({ method: "PUT" }),
    ));
  });

  it("shows a green probe and stays honest about which checks ran", async () => {
    mocks.fetch.mockImplementation((url: string) =>
      Promise.resolve(
        url.endsWith("/probe") && mocks.fetch.mock.calls.length > 1
          ? ok({ nonce: "n1", url: "https://x/probe/n1", verified: true, verified_from: "9.9.9.9" })
          : ok(
              configuredState({
                probe: { nonce: "n1", url: "https://x/probe/n1", verified: true, verified_from: "9.9.9.9" },
              }),
            ),
      ),
    );
    render(<RemoteAccessCard />);
    fireEvent.click(await screen.findByText("Remote access"));
    expect(await screen.findByText(/Verified: reachable from the internet/)).toBeTruthy();
    // Fail-closed copy stays visible even in the verified state.
    expect(screen.getByText("Remote mode activates only when every check above is green.")).toBeTruthy();
  });

  it("points at the A record when DNS does not match", async () => {
    mocks.fetch.mockResolvedValue(
      ok(
        configuredState({
          connectivity: {
            public_ip: "203.0.113.7",
            domain_addresses: ["192.0.2.9"],
            dns_matches_public_ip: false,
            tls_ok: false,
            tls_detail: "certificate not trusted",
            health_ok: false,
            health_detail: "HTTP 502",
            ingress_caddy: false,
          },
        }),
      ),
    );
    render(<RemoteAccessCard />);
    fireEvent.click(await screen.findByText("Remote access"));
    const dns = (await screen.findAllByText((_, element) =>
      element?.textContent?.startsWith("Domain does not point here yet") ?? false,
    ))[0];
    expect(dns.textContent).toContain("203.0.113.7");
    expect(
      screen.getAllByText((_, el) => el?.textContent?.startsWith("TLS handshake failed") ?? false)[0],
    ).toBeTruthy();
    expect(
      screen.getAllByText((_, el) => el?.textContent?.includes("--profile remote up -d caddy") ?? false)[0],
    ).toBeTruthy();
  });
});
