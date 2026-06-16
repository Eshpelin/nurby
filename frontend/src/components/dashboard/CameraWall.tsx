"use client";

// Customizable camera wall. A full-bleed mosaic where every tile can be
// dragged to reorder, resized (grid-span based, so it stays tidy), zoomed
// and panned into, blown up solo, and the whole wall taken to OS fullscreen.
// Layout (column count, order, per-tile span) persists per browser. The tile
// feed itself is rendered by the parent via `renderTile`, so this component
// owns only layout/interaction and never duplicates the feed plumbing.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

// A tile in the wall, camera or widget. The parent supplies the rendered
// node so the wall owns only layout/interaction, not the feed/data plumbing.
export interface WallItem {
  id: string;
  name: string;
  render: () => React.ReactNode;
}

const COLS_KEY = "nurby-wall-cols";
const ORDER_KEY = "nurby-wall-order";
const SPANS_KEY = "nurby-wall-spans";
const MAX_SPAN_H = 4;
const COL_CHOICES = [2, 3, 4, 6];

type Span = { w: number; h: number };

function loadJSON<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, n));

export function CameraWall({
  items,
  onExit,
  toolbarExtra,
}: {
  items: WallItem[];
  onExit?: () => void;
  toolbarExtra?: React.ReactNode;
}) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const gridRef = useRef<HTMLDivElement | null>(null);
  const [cols, setCols] = useState<number>(() => loadJSON(COLS_KEY, 3));
  const [order, setOrder] = useState<string[]>(() => loadJSON<string[]>(ORDER_KEY, []));
  const [spans, setSpans] = useState<Record<string, Span>>(() => loadJSON(SPANS_KEY, {}));
  const [rowH, setRowH] = useState(180);
  const [gridW, setGridW] = useState(0);
  const [solo, setSolo] = useState<string | null>(null);
  const [isFs, setIsFs] = useState(false);
  const dragId = useRef<string | null>(null);

  // Persist layout choices.
  useEffect(() => { try { localStorage.setItem(COLS_KEY, String(cols)); } catch { /* ignore */ } }, [cols]);
  useEffect(() => { try { localStorage.setItem(ORDER_KEY, JSON.stringify(order)); } catch { /* ignore */ } }, [order]);
  useEffect(() => { try { localStorage.setItem(SPANS_KEY, JSON.stringify(spans)); } catch { /* ignore */ } }, [spans]);

  // Keep the cell height ~16:9 of one column. Implicit rows are this tall, so
  // a 1x1 tile is a normal feed and taller spans grow vertically.
  useEffect(() => {
    const el = gridRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => {
      const w = el.clientWidth;
      setGridW(w);
      setRowH(Math.max(120, Math.round((w / cols) * (9 / 16))));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [cols]);

  // Track OS fullscreen so the button reflects reality (and Esc updates it).
  useEffect(() => {
    const onFs = () => setIsFs(!!document.fullscreenElement);
    document.addEventListener("fullscreenchange", onFs);
    return () => document.removeEventListener("fullscreenchange", onFs);
  }, []);

  // Esc closes a solo blow-up.
  useEffect(() => {
    if (!solo) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setSolo(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [solo]);

  // Reconcile the saved order with the live camera list: keep known ids in
  // their saved order, append any new cameras, drop any that vanished.
  const ordered = useMemo(() => {
    const byId = new Map(items.map((it) => [it.id, it]));
    const seen = new Set<string>();
    const out: WallItem[] = [];
    for (const id of order) {
      const it = byId.get(id);
      if (it && !seen.has(id)) { out.push(it); seen.add(id); }
    }
    for (const it of items) {
      if (!seen.has(it.id)) { out.push(it); seen.add(it.id); }
    }
    return out;
  }, [items, order]);

  const reorder = useCallback((fromId: string, toId: string) => {
    if (fromId === toId) return;
    setOrder(() => {
      const ids = ordered.map((it) => it.id);
      const from = ids.indexOf(fromId);
      const to = ids.indexOf(toId);
      if (from < 0 || to < 0) return ids;
      ids.splice(to, 0, ids.splice(from, 1)[0]);
      return ids;
    });
  }, [ordered]);

  const setSpan = useCallback((id: string, w: number, h: number) => {
    setSpans((prev) => ({ ...prev, [id]: { w: clamp(w, 1, cols), h: clamp(h, 1, MAX_SPAN_H) } }));
  }, [cols]);

  const toggleFullscreen = useCallback(() => {
    const el = rootRef.current;
    if (!el) return;
    if (document.fullscreenElement) document.exitFullscreen().catch(() => undefined);
    else el.requestFullscreen?.().catch(() => undefined);
  }, []);

  const resetLayout = useCallback(() => {
    setSpans({});
    setOrder(items.map((it) => it.id));
    setCols(3);
  }, [items]);

  const cellW = gridW > 0 ? gridW / cols : 0;
  const soloItem = solo ? items.find((it) => it.id === solo) : null;

  return (
    <div ref={rootRef} className="flex flex-col flex-1 min-h-0 bg-background">
      {/* Wall toolbar */}
      <div className="flex items-center justify-between gap-2 mb-2 flex-shrink-0">
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">Wall</span>
          <span className="text-[10px] text-muted-foreground/70 hidden sm:inline">
            drag header to move · drag corner to resize · scroll to zoom · double-click for solo
          </span>
        </div>
        <div className="flex items-center gap-2">
          {toolbarExtra}
          <div className="flex items-center gap-0.5 p-0.5 rounded bg-muted/50 border border-border">
            {COL_CHOICES.map((c) => (
              <button
                key={c}
                onClick={() => setCols(c)}
                className={`px-2 py-0.5 text-[11px] rounded transition-colors ${
                  cols === c ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                }`}
                title={`${c} columns`}
              >{c}</button>
            ))}
          </div>
          <button onClick={resetLayout}
            className="text-[11px] text-muted-foreground hover:text-foreground px-2 py-1 rounded hover:bg-muted/50 transition-colors"
            title="Reset wall layout">Reset</button>
          <button onClick={toggleFullscreen}
            className="text-[11px] px-2 py-1 rounded border border-border text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
            title="Toggle fullscreen">{isFs ? "Exit fullscreen" : "Fullscreen"}</button>
          {onExit && (
            <button onClick={onExit}
              className="text-[11px] px-2 py-1 rounded border border-border text-foreground hover:bg-muted/50 transition-colors"
              title="Back to the timeline dashboard">Exit wall</button>
          )}
        </div>
      </div>

      {/* Mosaic */}
      <div
        ref={gridRef}
        className="flex-1 overflow-y-auto scrollbar-thin"
        style={{
          display: "grid",
          gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`,
          gridAutoRows: `${rowH}px`,
          gridAutoFlow: "dense",
          gap: "0.4rem",
        }}
      >
        {ordered.map((it) => (
          <WallCell
            key={it.id}
            span={spans[it.id] || { w: 1, h: 1 }}
            cellW={cellW}
            rowH={rowH}
            onReorderDragStart={() => { dragId.current = it.id; }}
            onReorderDrop={() => { if (dragId.current) reorder(dragId.current, it.id); dragId.current = null; }}
            onResize={(w, h) => setSpan(it.id, w, h)}
            onSolo={() => setSolo(it.id)}
          >
            {it.render()}
          </WallCell>
        ))}
      </div>

      {/* Solo blow-up. Fills the viewport; Esc or the button closes it. */}
      {soloItem && (
        <div className="fixed inset-0 z-[60] bg-black/95 backdrop-blur-sm flex flex-col p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium text-white">{soloItem.name}</span>
            <button onClick={() => setSolo(null)}
              className="text-xs px-2 py-1 rounded border border-white/20 text-white/80 hover:bg-white/10">
              Close (Esc)
            </button>
          </div>
          <div className="flex-1 min-h-0">{soloItem.render()}</div>
        </div>
      )}
    </div>
  );
}

function WallCell({
  span,
  cellW,
  rowH,
  onReorderDragStart,
  onReorderDrop,
  onResize,
  onSolo,
  children,
}: {
  span: Span;
  cellW: number;
  rowH: number;
  onReorderDragStart: () => void;
  onReorderDrop: () => void;
  onResize: (w: number, h: number) => void;
  onSolo: () => void;
  children: React.ReactNode;
}) {
  const feedRef = useRef<HTMLDivElement | null>(null);
  const [zoom, setZoom] = useState({ scale: 1, x: 0, y: 0 });
  const [panning, setPanning] = useState(false);
  const pan = useRef<{ sx: number; sy: number; ox: number; oy: number } | null>(null);
  const resize = useRef<{ sx: number; sy: number; w: number; h: number } | null>(null);

  // Wheel zoom needs a non-passive listener to preventDefault the page scroll.
  useEffect(() => {
    const el = feedRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      setZoom((prev) => {
        const next = clamp(prev.scale * (e.deltaY < 0 ? 1.15 : 0.87), 1, 5);
        return next <= 1.001 ? { scale: 1, x: 0, y: 0 } : { ...prev, scale: next };
      });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  const onPointerDown = (e: React.PointerEvent) => {
    if (zoom.scale <= 1) return;
    if ((e.target as HTMLElement).closest("button")) return; // let tile controls work
    pan.current = { sx: e.clientX, sy: e.clientY, ox: zoom.x, oy: zoom.y };
    setPanning(true);
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!pan.current) return;
    setZoom((z) => ({ ...z, x: pan.current!.ox + (e.clientX - pan.current!.sx), y: pan.current!.oy + (e.clientY - pan.current!.sy) }));
  };
  const endPan = () => { pan.current = null; setPanning(false); };

  // Corner resize: snap the delta to whole cells.
  useEffect(() => {
    if (!resize.current) return;
    const onMove = (e: PointerEvent) => {
      const r = resize.current;
      if (!r || cellW <= 0) return;
      const w = r.w + Math.round((e.clientX - r.sx) / cellW);
      const h = r.h + Math.round((e.clientY - r.sy) / rowH);
      onResize(w, h);
    };
    const onUp = () => { resize.current = null; };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => { window.removeEventListener("pointermove", onMove); window.removeEventListener("pointerup", onUp); };
  });

  return (
    <div
      className="relative group/cell"
      style={{ gridColumn: `span ${span.w}`, gridRow: `span ${span.h}` }}
      onDragOver={(e) => e.preventDefault()}
      onDrop={onReorderDrop}
    >
      {/* Drag-to-move handle (top strip). Draggable so the whole tile is not. */}
      <div
        draggable
        onDragStart={onReorderDragStart}
        className="absolute top-0 left-0 right-0 h-5 z-20 cursor-move opacity-0 group-hover/cell:opacity-100 transition-opacity bg-gradient-to-b from-black/60 to-transparent flex items-center justify-center"
        title="Drag to move"
      >
        <span className="text-white/50 text-[10px] tracking-widest select-none">⠿</span>
      </div>

      {/* Feed with zoom/pan. transform scales the whole tile, so detection
          overlays stay aligned with the video. */}
      <div
        ref={feedRef}
        className="absolute inset-0 overflow-hidden rounded-lg"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endPan}
        onPointerLeave={endPan}
        onDoubleClick={onSolo}
        style={{ cursor: zoom.scale > 1 ? "grab" : "default" }}
      >
        <div
          className="w-full h-full"
          style={{
            transform: `translate(${zoom.x}px, ${zoom.y}px) scale(${zoom.scale})`,
            transformOrigin: "center center",
            transition: panning ? "none" : "transform 0.08s ease-out",
          }}
        >
          {children}
        </div>
      </div>

      {zoom.scale > 1 && (
        <button
          onClick={() => setZoom({ scale: 1, x: 0, y: 0 })}
          className="absolute bottom-1.5 left-1.5 z-20 text-[10px] px-1.5 py-0.5 rounded bg-black/70 text-white/80 border border-white/10 hover:bg-black/90"
          title="Reset zoom"
        >{zoom.scale.toFixed(1)}× · reset</button>
      )}

      {/* Resize grip (bottom-right corner). */}
      <div
        onPointerDown={(e) => {
          e.preventDefault();
          resize.current = { sx: e.clientX, sy: e.clientY, w: span.w, h: span.h };
        }}
        className="absolute bottom-0 right-0 z-20 w-4 h-4 cursor-nwse-resize opacity-0 group-hover/cell:opacity-100 transition-opacity"
        title="Drag to resize"
      >
        <svg viewBox="0 0 10 10" className="w-full h-full text-white/60">
          <path d="M9 1L1 9M9 5L5 9" stroke="currentColor" strokeWidth="1.2" fill="none" strokeLinecap="round" />
        </svg>
      </div>
    </div>
  );
}
