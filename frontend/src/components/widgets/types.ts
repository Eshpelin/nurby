// Dashboard widget types + the safe field resolver shared by the tile and
// the builder preview. A widget pulls JSON from an external API (proxied by
// the backend) and renders it either via a built-in template (field paths
// mapped onto Nurby components) or sandboxed custom HTML/JS.

export type WidgetRenderKind = "template" | "custom";
export type WidgetTemplateType = "stat" | "gauge" | "list" | "badge" | "text";
export type WidgetAuthKind = "none" | "bearer" | "header" | "query" | "basic";

export interface WidgetSource {
  url: string;
  method: "GET" | "POST";
  query?: Record<string, string>;
  headers?: Record<string, string>;
  body?: string | null;
  auth_kind: WidgetAuthKind;
  auth_name?: string | null;
  refresh_seconds: number;
}

export interface WidgetTemplate {
  type: WidgetTemplateType;
  // field name -> dot-path into the fetched JSON, e.g. "main.temp"
  bindings: Record<string, string>;
  options?: Record<string, unknown>;
}

export interface Widget {
  id: string;
  name: string;
  enabled: boolean;
  render_kind: WidgetRenderKind;
  source: WidgetSource | null;
  has_auth: boolean;
  template: WidgetTemplate | null;
  custom_html: string | null;
  layout: { w?: number; h?: number } | null;
  last_fetch_at: string | null;
  last_status: string | null;
  last_error: string | null;
  created_at: string;
}

export interface WidgetData {
  ok: boolean;
  status?: number | null;
  data?: unknown;
  fetched_at?: string | null;
  error?: string | null;
}

// Which bound fields each template understands, for the builder UI.
export const TEMPLATE_FIELDS: Record<WidgetTemplateType, { key: string; label: string; hint?: string }[]> = {
  stat: [
    { key: "value", label: "Value", hint: "e.g. main.temp" },
    { key: "unit", label: "Unit", hint: "static text or a path" },
    { key: "label", label: "Label" },
    { key: "sublabel", label: "Sub-label" },
  ],
  gauge: [
    { key: "value", label: "Value" },
    { key: "min", label: "Min", hint: "default 0" },
    { key: "max", label: "Max", hint: "default 100" },
    { key: "label", label: "Label" },
  ],
  list: [
    { key: "items", label: "Items (array path)", hint: "path to an array" },
    { key: "itemLabel", label: "Item label key", hint: "key within each item" },
    { key: "itemValue", label: "Item value key" },
  ],
  badge: [
    { key: "value", label: "Value" },
    { key: "label", label: "Label" },
  ],
  text: [
    { key: "text", label: "Text", hint: "path to a string" },
  ],
};

export const TEMPLATE_LABELS: Record<WidgetTemplateType, string> = {
  stat: "Stat (big number)",
  gauge: "Gauge (progress)",
  list: "List (rows)",
  badge: "Badge (status pill)",
  text: "Text",
};

// Safe dot-path resolver. Supports object keys and numeric array indices:
// "weather.0.main.temp". Returns undefined for any miss. No eval, no code.
export function resolvePath(obj: unknown, path: string | undefined): unknown {
  if (!path) return undefined;
  return path.split(".").reduce<unknown>((acc, key) => {
    if (acc == null) return undefined;
    if (Array.isArray(acc)) {
      const i = Number(key);
      return Number.isInteger(i) ? acc[i] : undefined;
    }
    if (typeof acc === "object") return (acc as Record<string, unknown>)[key];
    return undefined;
  }, obj);
}

// A bound field is either a literal (no matching path) or a resolved value.
// If the path resolves to something, use it; otherwise treat the binding
// string as a literal (so "Unit" can be the static "°C").
export function resolveOrLiteral(data: unknown, binding: string | undefined): unknown {
  if (binding == null || binding === "") return undefined;
  const resolved = resolvePath(data, binding);
  return resolved === undefined ? binding : resolved;
}

export function asText(v: unknown): string {
  if (v == null) return "";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}
