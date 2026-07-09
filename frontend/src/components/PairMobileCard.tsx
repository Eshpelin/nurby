"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { useAuth } from "@/lib/auth";

type PairStart = {
  code: string;
  expires_in: number;
  server_url: string | null;
};

/** Best guess at an API base URL the phone can reach. Prefers the
 * backend-configured public URL, then NEXT_PUBLIC_API_URL with a
 * localhost host swapped for the host the browser is actually on
 * (a phone cannot reach the desktop's "localhost"). */
function guessServerUrl(fromApi: string | null): string {
  if (fromApi) return fromApi.replace(/\/+$/, "");
  const host = window.location.hostname;
  const envUrl = process.env.NEXT_PUBLIC_API_URL;
  if (envUrl) {
    try {
      const u = new URL(envUrl);
      if (u.hostname === "localhost" || u.hostname === "127.0.0.1") {
        u.hostname = host;
      }
      return u.origin;
    } catch {
      // fall through to same-origin
    }
  }
  return window.location.origin;
}

/** Settings card that pairs the mobile app by QR code: fetches a
 * short-lived single-use code from /api/auth/pair/start and renders it
 * with the server URL. Scanning it logs the phone in as this user. */
export function PairMobileCard() {
  const { authFetch } = useAuth();
  const [open, setOpen] = useState(false);
  const [pair, setPair] = useState<PairStart | null>(null);
  const [serverUrl, setServerUrl] = useState("");
  const [secondsLeft, setSecondsLeft] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchCode = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await authFetch("/api/auth/pair/start", { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: PairStart = await res.json();
      setPair(data);
      setSecondsLeft(data.expires_in);
      setServerUrl((prev) => prev || guessServerUrl(data.server_url));
    } catch {
      setError("Could not create a pairing code.");
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  // Countdown while a code is showing.
  useEffect(() => {
    if (!open || !pair) return;
    timerRef.current = setInterval(
      () => setSecondsLeft((s) => Math.max(0, s - 1)),
      1000,
    );
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [open, pair]);

  useEffect(() => {
    if (open && !pair) void fetchCode();
  }, [open, pair, fetchCode]);

  const expired = pair !== null && secondsLeft === 0;
  const payload =
    pair && serverUrl
      ? JSON.stringify({ v: 1, url: serverUrl.replace(/\/+$/, ""), code: pair.code })
      : null;

  return (
    <div className="rounded-lg border border-border bg-card">
      <button
        onClick={() => setOpen(!open)}
        className="w-full px-4 py-3.5 flex items-center justify-between text-left"
      >
        <div className="flex items-center gap-3">
          <span className="w-2.5 h-2.5 rounded-full flex-shrink-0 bg-blue-500" />
          <div>
            <div className="text-sm font-medium">Mobile app</div>
            <div className="text-xs text-muted-foreground mt-0.5">
              Pair a phone by scanning a QR code
            </div>
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
        <div className="px-4 pb-4 border-t border-border pt-4">
          <div className="flex flex-col items-center gap-3">
            {error && <p className="text-sm text-red-500">{error}</p>}

            {payload && !expired && (
              <>
                <div className="rounded-lg bg-white p-3">
                  <QRCodeSVG value={payload} size={208} marginSize={0} />
                </div>
                <p className="text-xs text-muted-foreground text-center max-w-xs">
                  Open the Nurby app and tap &ldquo;Scan QR code&rdquo;. The code
                  signs the phone in as you and expires in {secondsLeft}s.
                </p>
              </>
            )}

            {expired && (
              <p className="text-sm text-muted-foreground">Code expired.</p>
            )}

            {(expired || error) && (
              <button
                onClick={() => void fetchCode()}
                disabled={loading}
                className="px-3 py-1.5 rounded-md border border-border text-sm hover:bg-muted transition-colors disabled:opacity-50"
              >
                {loading ? "Generating." : "New code"}
              </button>
            )}

            <div className="w-full max-w-xs">
              <label className="block text-xs text-muted-foreground mb-1">
                Server address the phone should use
              </label>
              <input
                value={serverUrl}
                onChange={(e) => setServerUrl(e.target.value)}
                placeholder="http://192.168.1.50:4748"
                className="w-full px-3 py-2 rounded-md border border-border bg-background text-sm"
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
