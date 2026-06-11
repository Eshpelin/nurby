"use client";

// WebSocket client for an in-flight AgentRun. Connects to
// /ws/agent/{runId}, auto-replays missed events using after_seq, and
// reconnects on transient drops up to 5 attempts with exponential
// backoff. Terminates cleanly on done / error / cancelled frames.

import { useCallback, useEffect, useRef, useState } from "react";

export type AgentEventType =
  | "plan"
  | "tool_start"
  | "tool_result"
  | "vlm_start"
  | "vlm_result"
  | "synthesis_token"
  | "done"
  | "error"
  | "cancelled"
  | "budget_warning"
  | "clarification";

export interface AgentEvent {
  type: AgentEventType;
  seq: number;
  ts?: string;
  // Loose payload bag. Each event type carries its own fields.
  // We keep the typing wide here and narrow at the use site so a
  // schema bump on the backend never crashes the chat surface.
  [k: string]: unknown;
}

export type StreamStatus = "idle" | "connecting" | "open" | "closed" | "error";

export interface UseAgentRunStreamResult {
  events: AgentEvent[];
  status: StreamStatus;
  error: string | null;
  lastSeq: number;
  reset: () => void;
}

const MAX_RETRIES = 5;
const BASE_BACKOFF_MS = 500;
const TERMINAL_TYPES = new Set<AgentEventType>(["done", "error", "cancelled"]);

export function useAgentRunStream(
  runId: string | null,
  token: string | null,
): UseAgentRunStreamResult {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [status, setStatus] = useState<StreamStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [lastSeq, setLastSeq] = useState<number>(0);
  const retryRef = useRef<number>(0);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closedByUs = useRef<boolean>(false);
  const lastSeqRef = useRef<number>(0);

  const reset = useCallback(() => {
    closedByUs.current = true;
    if (wsRef.current) {
      try { wsRef.current.close(); } catch {/* ignore */}
      wsRef.current = null;
    }
    if (reconnectTimer.current) {
      clearTimeout(reconnectTimer.current);
      reconnectTimer.current = null;
    }
    retryRef.current = 0;
    lastSeqRef.current = 0;
    setEvents([]);
    setStatus("idle");
    setError(null);
    setLastSeq(0);
  }, []);

  useEffect(() => {
    if (!runId || !token) return;
    closedByUs.current = false;

    const connect = () => {
      setStatus("connecting");
      const proto = window.location.protocol === "https." ? "wss." : "ws.";
      const scheme = window.location.protocol === "https:" ? "wss" : "ws";
      void proto;
      const explicitWs = process.env.NEXT_PUBLIC_WS_URL;
      // Next rewrites do not proxy WS upgrades; honor the configured endpoint.
      const wsBase = explicitWs ? explicitWs.replace(/^http/, "ws").replace(/\/+$/, "") : `${scheme}://${window.location.host}`;
      const url = `${wsBase}/ws/agent/${runId}?token=${encodeURIComponent(token)}&after_seq=${lastSeqRef.current}`;
      let ws: WebSocket;
      try {
        ws = new WebSocket(url);
      } catch (e) {
        setStatus("error");
        setError(e instanceof Error ? e.message : "ws construct failed");
        return;
      }
      wsRef.current = ws;

      ws.onopen = () => {
        setStatus("open");
        retryRef.current = 0;
        setError(null);
      };
      ws.onmessage = (ev) => {
        let parsed: AgentEvent | null = null;
        try {
          parsed = JSON.parse(ev.data) as AgentEvent;
        } catch {
          return;
        }
        if (!parsed || typeof parsed.type !== "string") return;
        if (typeof parsed.seq === "number" && parsed.seq > lastSeqRef.current) {
          lastSeqRef.current = parsed.seq;
          setLastSeq(parsed.seq);
        }
        setEvents((prev) => [...prev, parsed!]);
        if (TERMINAL_TYPES.has(parsed.type)) {
          closedByUs.current = true;
          try { ws.close(); } catch {/* ignore */}
          setStatus("closed");
        }
      };
      ws.onerror = () => {
        setError("websocket error");
      };
      ws.onclose = () => {
        wsRef.current = null;
        if (closedByUs.current) {
          setStatus("closed");
          return;
        }
        if (retryRef.current >= MAX_RETRIES) {
          setStatus("error");
          setError("disconnected after max retries");
          return;
        }
        const backoff = BASE_BACKOFF_MS * Math.pow(2, retryRef.current);
        retryRef.current += 1;
        reconnectTimer.current = setTimeout(connect, backoff);
      };
    };

    connect();
    return () => {
      closedByUs.current = true;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (wsRef.current) {
        try { wsRef.current.close(); } catch {/* ignore */}
      }
      wsRef.current = null;
    };
  }, [runId, token]);

  return { events, status, error, lastSeq, reset };
}
