"use client";

// Remote access wizard (#183): detects the network situation and walks
// the admin through the domain path — one HTTPS ingress, automatic TLS,
// and a phone-assisted reachability probe. Fails closed: nothing reads
// "verified" until the probe request lands from a public address over
// HTTPS; every other check being green is displayed, never assumed.

import { useCallback, useEffect, useRef, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { useAuth } from "@/lib/auth";
import { translate } from "@/lib/i18n";

type Connectivity = {
  public_ip: string | null;
  domain_addresses: string[];
  dns_matches_public_ip: boolean | null;
  tls_ok: boolean | null;
  tls_detail: string | null;
  health_ok: boolean | null;
  health_detail: string | null;
  ingress_caddy: boolean;
};

type Probe = {
  nonce: string;
  url: string;
  verified: boolean;
  verified_from: string | null;
};

type RemoteAccessState = {
  configured: boolean;
  domain: string | null;
  scheme: string | null;
  public_base_url: string | null;
  connectivity: Connectivity | null;
  probe: Probe | null;
};

function Check({ ok, children }: { ok: boolean | null; children: React.ReactNode }) {
  const color =
    ok === true ? "bg-green-500" : ok === false ? "bg-red-500" : "bg-muted-foreground/40";
  return (
    <li className="flex items-start gap-2 text-xs">
      <span className={`mt-1 w-2 h-2 rounded-full flex-shrink-0 ${color}`} />
      <span className="text-muted-foreground">{children}</span>
    </li>
  );
}

export function RemoteAccessCard() {
  const { authFetch, user } = useAuth();
  const t = useCallback(
    (key: string, values?: Record<string, string | number>) =>
      translate(user?.locale, key, values),
    [user?.locale],
  );
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<RemoteAccessState | null>(null);
  const [domainInput, setDomainInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadState = useCallback(async () => {
    try {
      const res = await authFetch("/api/system/remote-access");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setState((await res.json()) as RemoteAccessState);
    } catch {
      setError(t("remote_access.load_failed"));
    }
  }, [authFetch, t]);

  useEffect(() => {
    if (open && !state) void loadState();
  }, [open, state, loadState]);

  // While a probe is outstanding, poll its status; stop once verified.
  useEffect(() => {
    const probe = state?.probe;
    if (!open || !probe || probe.verified) {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
      return;
    }
    pollRef.current = setInterval(async () => {
      try {
        const res = await authFetch("/api/system/remote-access/probe");
        if (!res.ok) return;
        const probe = (await res.json()) as Probe | null;
        if (probe) setState((prev) => (prev ? { ...prev, probe } : prev));
      } catch {
        // transient; the next tick retries
      }
    }, 4000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
    };
  }, [open, state?.probe, authFetch]);

  const submitDomain = async () => {
    const domain = domainInput.trim();
    if (!domain) return;
    setBusy(true);
    setError(null);
    try {
      const res = await authFetch("/api/system/remote-access/domain", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ domain }),
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => null)) as { detail?: string } | null;
        throw new Error(body?.detail ?? `HTTP ${res.status}`);
      }
      setState((await res.json()) as RemoteAccessState);
      setDomainInput("");
    } catch (e) {
      setError(e instanceof Error ? e.message : t("remote_access.load_failed"));
    } finally {
      setBusy(false);
    }
  };

  const disableRemote = async () => {
    setBusy(true);
    try {
      const res = await authFetch("/api/system/remote-access/domain", { method: "DELETE" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setState((await res.json()) as RemoteAccessState);
    } catch {
      setError(t("remote_access.load_failed"));
    } finally {
      setBusy(false);
    }
  };

  const startProbe = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await authFetch("/api/system/remote-access/probe", { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const probe = (await res.json()) as Probe;
      setState((prev) => (prev ? { ...prev, probe } : prev));
    } catch {
      setError(t("remote_access.load_failed"));
    } finally {
      setBusy(false);
    }
  };

  const configured = state?.configured ?? false;
  const c = state?.connectivity ?? null;
  const probe = state?.probe ?? null;

  return (
    <div id="remote-access" className="rounded-lg border border-border bg-card scroll-mt-20">
      <button
        onClick={() => setOpen(!open)}
        className="w-full px-4 py-3.5 flex items-center justify-between text-left"
      >
        <div className="flex items-center gap-3">
          <span
            className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${
              probe?.verified ? "bg-green-500" : configured ? "bg-amber-500" : "bg-muted-foreground/40"
            }`}
          />
          <div>
            <div className="text-sm font-medium">{t("remote_access.title")}</div>
            <div className="text-xs text-muted-foreground mt-0.5">{t("remote_access.subtitle")}</div>
          </div>
        </div>
        <svg
          width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
          className={`text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`}
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>

      {open && (
        <div className="px-4 pb-4 border-t border-border pt-4 space-y-4">
          {error && <p className="text-sm text-red-500">{error}</p>}

          {!configured && (
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">{t("remote_access.not_configured")}</p>
              <label className="block text-xs text-muted-foreground" htmlFor="remote-access-domain">
                {t("remote_access.domain_label")}
              </label>
              <div className="flex gap-2 max-w-sm">
                <input
                  id="remote-access-domain"
                  value={domainInput}
                  onChange={(e) => setDomainInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && void submitDomain()}
                  placeholder="camera.example.com"
                  className="flex-1 px-3 py-2 rounded-md border border-border bg-background text-sm"
                />
                <button
                  onClick={() => void submitDomain()}
                  disabled={busy || !domainInput.trim()}
                  className="px-3 py-2 rounded-md bg-foreground text-background text-sm font-medium hover:opacity-90 disabled:opacity-50"
                >
                  {busy ? t("remote_access.saving") : t("remote_access.use_domain")}
                </button>
              </div>
              <p className="text-xs text-muted-foreground">{t("remote_access.prereq")}</p>
            </div>
          )}

          {configured && (
            <>
              <div className="flex items-center justify-between">
                <p className="text-xs">
                  {t("remote_access.configured_for", { domain: state?.domain ?? "" })}
                </p>
                <button
                  onClick={() => void disableRemote()}
                  disabled={busy}
                  className="text-xs px-2 py-1 rounded-md border border-border hover:bg-muted disabled:opacity-50"
                >
                  {t("remote_access.disable")}
                </button>
              </div>

              {c && (
                <div>
                  <p className="text-xs font-medium mb-1.5">{t("remote_access.checks")}</p>
                  <ul className="space-y-1.5">
                    <Check ok={c.public_ip !== null}>
                      {c.public_ip
                        ? t("remote_access.public_ip_value", { ip: c.public_ip })
                        : t("remote_access.public_ip_unknown")}
                    </Check>
                    <Check ok={c.dns_matches_public_ip}>
                      {c.dns_matches_public_ip
                        ? t("remote_access.dns_ok")
                        : c.public_ip
                          ? t("remote_access.dns_mismatch", {
                              domain: state?.domain ?? "",
                              ip: c.public_ip,
                            })
                          : t("remote_access.dns_missing")}
                    </Check>
                    <Check ok={c.tls_ok}>
                      {c.tls_ok === null
                        ? t("remote_access.tls_pending")
                        : c.tls_ok
                          ? t("remote_access.tls_ok", { detail: c.tls_detail ?? "" })
                          : t("remote_access.tls_fail", { detail: c.tls_detail ?? "" })}
                    </Check>
                    <Check ok={c.health_ok}>
                      {c.health_ok
                        ? t("remote_access.health_ok")
                        : t("remote_access.health_fail", { detail: c.health_detail ?? "" })}
                    </Check>
                    <Check ok={c.ingress_caddy}>
                      {c.ingress_caddy
                        ? t("remote_access.ingress_ok")
                        : t("remote_access.ingress_missing", { domain: state?.domain ?? "" })}
                    </Check>
                  </ul>
                </div>
              )}

              <div className="border-t border-border pt-3 space-y-2">
                <p className="text-xs font-medium">{t("remote_access.probe_title")}</p>
                <p className="text-xs text-muted-foreground">{t("remote_access.probe_intro")}</p>

                {probe?.verified ? (
                  <p className="text-xs text-green-600 font-medium flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-green-500" />
                    {t("remote_access.probe_verified")}
                  </p>
                ) : probe ? (
                  <div className="space-y-2">
                    <div className="rounded-lg bg-white p-3 w-fit">
                      <QRCodeSVG value={probe.url} size={168} marginSize={0} />
                    </div>
                    <p className="text-xs text-amber-600 flex items-center gap-1.5">
                      <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse" />
                      {t("remote_access.probe_waiting")}
                    </p>
                  </div>
                ) : (
                  <button
                    onClick={() => void startProbe()}
                    disabled={busy}
                    className="px-3 py-1.5 rounded-md border border-border text-xs hover:bg-muted disabled:opacity-50"
                  >
                    {t("remote_access.probe_start")}
                  </button>
                )}
                <p className="text-xs text-muted-foreground">{t("remote_access.fail_closed")}</p>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
