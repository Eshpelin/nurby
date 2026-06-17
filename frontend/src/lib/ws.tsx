"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { useAuth } from "@/lib/auth";

/**
 * Shared /ws subscription. Mounted once at the dashboard root, fans
 * out events to subscribers via a small pub/sub. Replaces N tile-
 * scoped sockets with a single connection.
 *
 * Reconnect uses capped exponential backoff (1s, 2s, 4s, ..., 30s).
 * Subscribers register handlers per ``type``; ``"*"`` is the
 * wildcard. Camera filtering happens in the subscriber.
 */

export type WSMessage = {
  type: string;
  camera_id?: string;
  [key: string]: unknown;
};

/**
 * Connection lifecycle, surfaced to the UI so a dropped live feed reads
 * as "paused, reconnecting" rather than silently going stale.
 *
 * - ``connecting``    first attempt, no socket has opened yet.
 * - ``connected``     socket is open and live data is flowing.
 * - ``reconnecting``  socket dropped after a prior success; backing off.
 * - ``disconnected``  provider unmounted / closed for good.
 */
export type WSStatus = "connecting" | "connected" | "reconnecting" | "disconnected";

type Handler = (msg: WSMessage) => void;

interface WSContextValue {
  /** Convenience: true only while the socket is open. */
  connected: boolean;
  /** Full lifecycle state for status indicators. */
  status: WSStatus;
  subscribe: (type: string, handler: Handler) => () => void;
}

const WSContext = createContext<WSContextValue | null>(null);

export function WebSocketProvider({ children }: { children: React.ReactNode }) {
  const { token } = useAuth();
  const [status, setStatus] = useState<WSStatus>("connecting");
  const wsRef = useRef<WebSocket | null>(null);
  const handlersRef = useRef<Map<string, Set<Handler>>>(new Map());

  useEffect(() => {
    if (typeof window === "undefined") return;
    // The /ws socket is now token-authenticated (issue #40). Don't open it
    // until we have a token; the effect re-runs when one appears (login /
    // bootstrap) and tears down the old socket if the token changes or
    // clears (logout). Stay in "connecting" while unauthenticated so the
    // UI reads as "waiting" rather than a hard failure.
    if (!token) {
      setStatus("connecting");
      return;
    }
    const explicit = process.env.NEXT_PUBLIC_WS_URL;
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    // Next.js rewrites do not proxy WebSocket upgrades, so same-origin /ws
    // only works when the API itself serves the page. Use the configured
    // WS endpoint (compose passes NEXT_PUBLIC_WS_URL) and fall back to
    // same-origin for setups that terminate WS at a real reverse proxy.
    const WSURL_BASE = explicit
      ? explicit.replace(/^http/, "ws").replace(/\/+$/, "")
      : `${protocol}//${window.location.host}`;
    const url = `${WSURL_BASE}/ws?token=${encodeURIComponent(token)}`;

    let cancelled = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;

    const scheduleReconnect = () => {
      if (cancelled) return;
      // Once we've ever connected, a drop is a "reconnecting" state; the
      // initial pre-open failures stay as "connecting" so a never-up feed
      // doesn't flash a misleading "reconnecting" badge.
      setStatus((s) => (s === "connecting" ? "connecting" : "reconnecting"));
      attempt = Math.min(attempt + 1, 6);
      // Capped exponential backoff: 1s, 2s, 4s, 8s, 16s, 30s (cap).
      const delay = Math.min(30000, 1000 * 2 ** (attempt - 1));
      reconnectTimer = setTimeout(connect, delay);
    };

    const connect = () => {
      if (cancelled) return;
      try {
        const ws = new WebSocket(url);
        wsRef.current = ws;
        ws.onopen = () => {
          attempt = 0;
          setStatus("connected");
        };
        ws.onmessage = (evt) => {
          let msg: WSMessage | null = null;
          try {
            msg = JSON.parse(evt.data);
          } catch {
            return;
          }
          if (!msg || typeof msg.type !== "string") return;
          // Fan out to type-specific and wildcard subscribers.
          const direct = handlersRef.current.get(msg.type);
          const wild = handlersRef.current.get("*");
          if (direct) direct.forEach((h) => safe(h, msg!));
          if (wild) wild.forEach((h) => safe(h, msg!));
        };
        ws.onclose = () => {
          if (cancelled) return;
          scheduleReconnect();
        };
        ws.onerror = () => ws.close();
      } catch {
        scheduleReconnect();
      }
    };

    connect();
    return () => {
      cancelled = true;
      setStatus("disconnected");
      if (reconnectTimer) clearTimeout(reconnectTimer);
      try {
        wsRef.current?.close();
      } catch {
        /* ignore */
      }
    };
  }, [token]);

  const value = useMemo<WSContextValue>(
    () => ({
      connected: status === "connected",
      status,
      subscribe(type, handler) {
        const map = handlersRef.current;
        let bucket = map.get(type);
        if (!bucket) {
          bucket = new Set();
          map.set(type, bucket);
        }
        bucket.add(handler);
        return () => {
          bucket!.delete(handler);
          if (bucket!.size === 0) map.delete(type);
        };
      },
    }),
    [status]
  );

  return <WSContext.Provider value={value}>{children}</WSContext.Provider>;
}

export function useWebSocket(): WSContextValue {
  const ctx = useContext(WSContext);
  if (!ctx) {
    // Provider not mounted. Return a no-op so a component can render
    // outside the dashboard without crashing.
    return {
      connected: false,
      status: "disconnected",
      subscribe: () => () => {},
    };
  }
  return ctx;
}

/**
 * Subscribe to one or more WS types and run ``handler`` for each
 * matching message. Optional ``cameraId`` filter pre-checks
 * ``msg.camera_id`` so subscribers don't repeat the boilerplate.
 */
export function useWSSubscribe(
  types: string | string[],
  handler: Handler,
  cameraId?: string
) {
  const ctx = useContext(WSContext);
  const handlerRef = useRef(handler);
  handlerRef.current = handler;
  useEffect(() => {
    if (!ctx) return;
    const list = Array.isArray(types) ? types : [types];
    const unsubs = list.map((t) =>
      ctx.subscribe(t, (msg) => {
        if (cameraId && msg.camera_id && msg.camera_id !== cameraId) return;
        handlerRef.current(msg);
      })
    );
    return () => {
      for (const u of unsubs) u();
    };
    // types may be a literal array; serialize for stable deps.
  }, [ctx, cameraId, Array.isArray(types) ? types.join("|") : types]); // eslint-disable-line react-hooks/exhaustive-deps
}

function safe(h: Handler, msg: WSMessage) {
  try {
    h(msg);
  } catch {
    /* swallow handler errors */
  }
}
