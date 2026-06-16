"use client";

// A dashboard widget rendered as a wall tile. Polls the backend proxy
// (/api/widgets/{id}/data) on the widget's refresh interval, surfaces
// loading/error state (never silent), and renders via WidgetView. Edit and
// delete live in a hover header, mirroring the camera tile's controls.

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";
import { timeAgo } from "@/lib/time";
import { WidgetView } from "@/components/widgets/WidgetView";
import type { Widget, WidgetData } from "@/components/widgets/types";

export function WidgetTile({
  widget,
  onEdit,
  onDelete,
}: {
  widget: Widget;
  onEdit: (w: Widget) => void;
  onDelete: (w: Widget) => void;
}) {
  const { authFetch } = useAuth();
  const [result, setResult] = useState<WidgetData | null>(null);
  const [loading, setLoading] = useState(true);
  const mounted = useRef(true);

  const refresh = Math.max(10, widget.source?.refresh_seconds || 60);

  const poll = useCallback(async () => {
    try {
      const res = await authFetch(`/api/widgets/${widget.id}/data`);
      if (!mounted.current) return;
      if (res.ok) setResult(await res.json());
      else setResult({ ok: false, error: `fetch failed (${res.status})` });
    } catch (e) {
      if (mounted.current) setResult({ ok: false, error: String(e) });
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, [authFetch, widget.id]);

  useEffect(() => {
    mounted.current = true;
    setLoading(true);
    if (!widget.enabled) { setLoading(false); return; }
    poll();
    const t = setInterval(poll, refresh * 1000);
    return () => { mounted.current = false; clearInterval(t); };
  }, [poll, refresh, widget.enabled]);

  const failed = result && !result.ok;

  return (
    <div className="h-full flex flex-col rounded-lg border border-border bg-card overflow-hidden group/widget">
      {/* Header */}
      <div className="flex items-center gap-1.5 px-2.5 py-1.5 border-b border-border/60 flex-shrink-0">
        <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
          !widget.enabled ? "bg-gray-500" : failed ? "bg-rose-500" : "bg-green-500"
        }`} />
        <span className="text-xs font-medium text-foreground truncate flex-1">{widget.name}</span>
        <button onClick={() => onEdit(widget)}
          className="opacity-0 group-hover/widget:opacity-100 transition-opacity text-muted-foreground hover:text-foreground"
          title="Edit widget" aria-label="Edit widget">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
        </button>
        <button onClick={() => onDelete(widget)}
          className="opacity-0 group-hover/widget:opacity-100 transition-opacity text-muted-foreground hover:text-rose-400"
          title="Delete widget" aria-label="Delete widget">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/></svg>
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 min-h-0 relative">
        {!widget.enabled ? (
          <div className="w-full h-full flex items-center justify-center text-xs text-muted-foreground">Disabled</div>
        ) : loading ? (
          <div className="w-full h-full flex items-center justify-center">
            <svg className="animate-spin h-4 w-4 text-muted-foreground" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          </div>
        ) : failed ? (
          <div className="w-full h-full flex flex-col items-center justify-center gap-1 px-3 text-center">
            <span className="text-xs text-rose-300">Couldn&apos;t load</span>
            <span className="text-[10px] text-muted-foreground break-words line-clamp-3">{result?.error}</span>
          </div>
        ) : (
          <WidgetView widget={widget} data={result?.data} />
        )}
      </div>

      {/* Footer: last updated */}
      {widget.enabled && result?.fetched_at && !failed && (
        <div className="px-2.5 py-1 border-t border-border/40 text-[10px] text-muted-foreground flex-shrink-0">
          updated {timeAgo(result.fetched_at)}
        </div>
      )}
    </div>
  );
}
