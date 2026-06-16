"use client";

// Pure renderer for a widget given its fetched data. Used by both the live
// tile and the builder preview. Templates map field paths onto Nurby's own
// look; the "custom" kind renders user HTML/JS in a locked-down iframe.

import { useEffect, useMemo, useRef } from "react";
import {
  asText,
  resolveOrLiteral,
  resolvePath,
  type Widget,
  type WidgetTemplateType,
} from "./types";

export function WidgetView({ widget, data }: { widget: Widget; data: unknown }) {
  if (widget.render_kind === "custom") {
    return <CustomWidget html={widget.custom_html || ""} data={data} />;
  }
  const t = widget.template;
  if (!t) return <Centered>No template configured</Centered>;
  const b = t.bindings || {};
  switch (t.type as WidgetTemplateType) {
    case "stat": return <StatView data={data} b={b} />;
    case "gauge": return <GaugeView data={data} b={b} />;
    case "list": return <ListView data={data} b={b} />;
    case "badge": return <BadgeView data={data} b={b} />;
    case "text": return <TextView data={data} b={b} />;
    default: return <Centered>Unknown template</Centered>;
  }
}

function Centered({ children }: { children: React.ReactNode }) {
  return <div className="w-full h-full flex items-center justify-center text-xs text-muted-foreground p-3 text-center">{children}</div>;
}

type Bindings = Record<string, string>;

function StatView({ data, b }: { data: unknown; b: Bindings }) {
  const value = resolveOrLiteral(data, b.value);
  const unit = resolveOrLiteral(data, b.unit);
  const label = resolveOrLiteral(data, b.label);
  const sublabel = resolveOrLiteral(data, b.sublabel);
  return (
    <div className="w-full h-full flex flex-col justify-center px-4 py-3">
      {label != null && <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-1 truncate">{asText(label)}</div>}
      <div className="flex items-baseline gap-1">
        <span className="text-3xl font-semibold text-foreground tabular-nums truncate">{asText(value) || "—"}</span>
        {unit != null && unit !== "" && <span className="text-sm text-muted-foreground">{asText(unit)}</span>}
      </div>
      {sublabel != null && sublabel !== "" && <div className="text-xs text-muted-foreground mt-1 truncate">{asText(sublabel)}</div>}
    </div>
  );
}

function GaugeView({ data, b }: { data: unknown; b: Bindings }) {
  const value = Number(resolveOrLiteral(data, b.value)) || 0;
  const min = Number(resolveOrLiteral(data, b.min) ?? 0) || 0;
  const max = Number(resolveOrLiteral(data, b.max) ?? 100) || 100;
  const label = resolveOrLiteral(data, b.label);
  const pct = max > min ? Math.max(0, Math.min(1, (value - min) / (max - min))) : 0;
  return (
    <div className="w-full h-full flex flex-col justify-center px-4 py-3">
      {label != null && <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-1 truncate">{asText(label)}</div>}
      <div className="flex items-baseline gap-1 mb-2">
        <span className="text-2xl font-semibold text-foreground tabular-nums">{asText(value)}</span>
      </div>
      <div className="h-2 rounded-full bg-muted overflow-hidden">
        <div className="h-full rounded-full bg-accent transition-[width]" style={{ width: `${Math.round(pct * 100)}%` }} />
      </div>
    </div>
  );
}

function ListView({ data, b }: { data: unknown; b: Bindings }) {
  const arr = resolvePath(data, b.items);
  const rows = Array.isArray(arr) ? arr : [];
  if (rows.length === 0) return <Centered>No items</Centered>;
  return (
    <div className="w-full h-full overflow-y-auto scrollbar-thin px-3 py-2 space-y-1">
      {rows.slice(0, 100).map((item, i) => {
        const label = b.itemLabel ? resolvePath(item, b.itemLabel) : item;
        const value = b.itemValue ? resolvePath(item, b.itemValue) : undefined;
        return (
          <div key={i} className="flex items-center justify-between gap-2 text-xs border-b border-border/40 pb-1">
            <span className="text-muted-foreground truncate">{asText(label)}</span>
            {value !== undefined && <span className="text-foreground tabular-nums flex-shrink-0">{asText(value)}</span>}
          </div>
        );
      })}
    </div>
  );
}

function BadgeView({ data, b }: { data: unknown; b: Bindings }) {
  const value = asText(resolveOrLiteral(data, b.value));
  const label = resolveOrLiteral(data, b.label);
  const tone = /^(ok|up|online|healthy|true|good)$/i.test(value)
    ? "bg-green-500/15 text-green-300 border-green-500/30"
    : /^(error|down|offline|fail|false|bad|critical)$/i.test(value)
      ? "bg-rose-500/15 text-rose-300 border-rose-500/30"
      : "bg-sky-500/15 text-sky-300 border-sky-500/30";
  return (
    <div className="w-full h-full flex flex-col items-center justify-center gap-2 px-3 py-3 text-center">
      {label != null && <div className="text-[11px] uppercase tracking-wider text-muted-foreground truncate">{asText(label)}</div>}
      <span className={`inline-flex items-center px-2.5 py-1 rounded-full border text-sm font-medium ${tone}`}>{value || "—"}</span>
    </div>
  );
}

function TextView({ data, b }: { data: unknown; b: Bindings }) {
  const text = resolveOrLiteral(data, b.text);
  return (
    <div className="w-full h-full overflow-y-auto scrollbar-thin px-4 py-3 text-sm text-foreground whitespace-pre-wrap break-words">
      {asText(text) || <span className="text-muted-foreground">No text</span>}
    </div>
  );
}

// Minimal CSS handed to custom widgets so they match the dark theme without
// any access to the parent stylesheet.
const CUSTOM_BASE_CSS = `
  :root { color-scheme: dark; }
  html,body { margin:0; height:100%; background:transparent;
    color:#fafafa; font-family: ui-sans-serif, system-ui, sans-serif; font-size:13px; }
  body { padding:10px; box-sizing:border-box; }
  a { color:#36d399; }
`;

function CustomWidget({ html, data }: { html: string; data: unknown }) {
  const ref = useRef<HTMLIFrameElement | null>(null);
  // srcDoc + sandbox="allow-scripts" (NO allow-same-origin) => unique opaque
  // origin: the script cannot read Nurby's cookies, localStorage, JWT, or the
  // parent DOM. Data is delivered by postMessage; we never post tokens.
  const srcDoc = useMemo(
    () =>
      `<!doctype html><html><head><meta charset="utf-8"><style>${CUSTOM_BASE_CSS}</style></head>` +
      `<body>${html}` +
      `<script>window.addEventListener("message",function(e){` +
      `if(e&&e.data&&e.data.__nurby){window.nurbyData=e.data.data;` +
      `document.dispatchEvent(new CustomEvent("nurbydata",{detail:e.data.data}));}});` +
      `</script></body></html>`,
    [html]
  );
  const post = () => {
    // Opaque-origin iframe => targetOrigin must be "*"; we only send the
    // already-fetched widget data, never auth tokens.
    ref.current?.contentWindow?.postMessage({ __nurby: true, data }, "*");
  };
  useEffect(() => { post(); });
  return (
    <iframe
      ref={ref}
      srcDoc={srcDoc}
      sandbox="allow-scripts"
      onLoad={post}
      className="w-full h-full border-0 bg-transparent"
      title="custom widget"
    />
  );
}
