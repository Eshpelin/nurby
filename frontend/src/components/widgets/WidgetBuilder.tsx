"use client";

// Create/edit modal for a dashboard widget. Mirrors the rule builder shape:
// labeled sections + a "Test" that dry-runs the source against the backend
// proxy (/api/widgets/test) and shows a live preview using the real renderer.

import { useEffect, useMemo, useState } from "react";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/lib/feedback";
import { WidgetView } from "./WidgetView";
import {
  TEMPLATE_FIELDS,
  TEMPLATE_LABELS,
  type Widget,
  type WidgetAuthKind,
  type WidgetData,
  type WidgetTemplateType,
} from "./types";

const AUTH_KINDS: { value: WidgetAuthKind; label: string }[] = [
  { value: "none", label: "None" },
  { value: "bearer", label: "Bearer token" },
  { value: "header", label: "Header" },
  { value: "query", label: "Query param" },
  { value: "basic", label: "Basic (user:pass)" },
];

const CUSTOM_SAMPLE = `<div id="root">Waiting…</div>
<script>
  document.addEventListener('nurbydata', function (e) {
    document.getElementById('root').textContent = JSON.stringify(e.detail);
  });
</script>`;

export function WidgetBuilder({
  widget,
  onClose,
  onSaved,
}: {
  widget: Widget | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { authFetch } = useAuth();
  const toast = useToast();
  const editing = !!widget;

  const [name, setName] = useState(widget?.name || "");
  const [renderKind, setRenderKind] = useState<"template" | "custom">(widget?.render_kind || "template");
  const [url, setUrl] = useState(widget?.source?.url || "");
  const [method, setMethod] = useState<"GET" | "POST">(widget?.source?.method || "GET");
  const [authKind, setAuthKind] = useState<WidgetAuthKind>(widget?.source?.auth_kind || "none");
  const [authName, setAuthName] = useState(widget?.source?.auth_name || "");
  const [authSecret, setAuthSecret] = useState("");
  const [clearSecret, setClearSecret] = useState(false);
  const [refresh, setRefresh] = useState(String(widget?.source?.refresh_seconds || 60));
  const [templateType, setTemplateType] = useState<WidgetTemplateType>(
    (widget?.template?.type as WidgetTemplateType) || "stat"
  );
  const [bindings, setBindings] = useState<Record<string, string>>(widget?.template?.bindings || {});
  const [customHtml, setCustomHtml] = useState(widget?.custom_html || CUSTOM_SAMPLE);

  const [testData, setTestData] = useState<WidgetData | null>(null);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const buildSource = () => ({
    url: url.trim(),
    method,
    auth_kind: authKind,
    auth_name: authName.trim() || null,
    refresh_seconds: Math.max(10, parseInt(refresh) || 60),
  });

  // Draft widget for the live preview (uses the real renderer).
  const draftWidget: Widget = useMemo(() => ({
    id: widget?.id || "preview",
    name: name || "Preview",
    enabled: true,
    render_kind: renderKind,
    source: { ...buildSource() },
    has_auth: false,
    template: { type: templateType, bindings },
    custom_html: customHtml,
    layout: null,
    last_fetch_at: null, last_status: null, last_error: null, created_at: "",
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [widget?.id, name, renderKind, url, method, authKind, authName, refresh, templateType, bindings, customHtml]);

  const runTest = async () => {
    setTesting(true);
    setTestData(null);
    try {
      const res = await authFetch("/api/widgets/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source: buildSource(),
          auth_secret: authSecret || null,
          widget_id: widget?.id || null,
        }),
      });
      const data = await res.json();
      setTestData(data);
      if (!data.ok) toast.error(data.error || "Test fetch failed");
    } catch (e) {
      toast.error(String(e));
    } finally {
      setTesting(false);
    }
  };

  const save = async () => {
    if (!name.trim()) { toast.error("Name is required"); return; }
    if (!url.trim()) { toast.error("URL is required"); return; }
    setSaving(true);
    try {
      const payload: Record<string, unknown> = {
        name: name.trim(),
        render_kind: renderKind,
        source: buildSource(),
        template: renderKind === "template" ? { type: templateType, bindings } : null,
        custom_html: renderKind === "custom" ? customHtml : null,
      };
      // Only touch the secret when the user typed one or explicitly cleared it.
      if (authSecret) payload.auth_secret = authSecret;
      else if (clearSecret) payload.auth_secret = "";
      const res = editing
        ? await authFetch(`/api/widgets/${widget!.id}`, {
            method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
          })
        : await authFetch("/api/widgets", {
            method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
          });
      if (res.ok) { toast.success(editing ? "Widget updated" : "Widget created"); onSaved(); }
      else { const e = await res.json().catch(() => ({})); toast.error(e.detail || "Save failed"); }
    } catch (e) {
      toast.error(String(e));
    } finally {
      setSaving(false);
    }
  };

  const input = "w-full px-2.5 py-1.5 rounded-md bg-background border border-border text-sm";
  const fields = TEMPLATE_FIELDS[templateType];

  return (
    <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-card border border-border rounded-lg w-full max-w-3xl max-h-[90vh] overflow-y-auto scrollbar-thin"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-3 border-b border-border sticky top-0 bg-card z-10">
          <h2 className="text-sm font-semibold">{editing ? "Edit widget" : "New widget"}</h2>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground text-lg leading-none">×</button>
        </div>

        <div className="p-5 grid md:grid-cols-2 gap-5">
          {/* Left: config */}
          <div className="space-y-3">
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Name</label>
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Living room temperature" className={input} />
            </div>

            <div>
              <label className="text-xs text-muted-foreground block mb-1">Data URL</label>
              <div className="flex gap-2">
                <select value={method} onChange={(e) => setMethod(e.target.value as "GET" | "POST")}
                  className="px-2 py-1.5 rounded-md bg-background border border-border text-sm">
                  <option>GET</option><option>POST</option>
                </select>
                <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="http://homeassistant.local/api/states/sensor.temp" className={input} />
              </div>
              <p className="text-[11px] text-muted-foreground mt-1">Nurby calls this server-side. LAN addresses are allowed; the key never reaches the browser.</p>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Auth</label>
                <select value={authKind} onChange={(e) => setAuthKind(e.target.value as WidgetAuthKind)} className={input}>
                  {AUTH_KINDS.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
                </select>
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Refresh (s)</label>
                <input type="number" min="10" value={refresh} onChange={(e) => setRefresh(e.target.value)} className={input} />
              </div>
            </div>

            {(authKind === "header" || authKind === "query") && (
              <div>
                <label className="text-xs text-muted-foreground block mb-1">{authKind === "header" ? "Header name" : "Query param name"}</label>
                <input value={authName} onChange={(e) => setAuthName(e.target.value)} placeholder={authKind === "header" ? "X-API-Key" : "api_key"} className={input} />
              </div>
            )}
            {authKind !== "none" && (
              <div>
                <label className="text-xs text-muted-foreground block mb-1">
                  {authKind === "basic" ? "user:password" : "Key / token"}
                  {editing && widget?.has_auth && !authSecret && <span className="text-muted-foreground"> (stored, leave blank to keep)</span>}
                </label>
                <input type="password" value={authSecret} onChange={(e) => setAuthSecret(e.target.value)}
                  placeholder={editing && widget?.has_auth ? "••••••••" : ""} className={input} />
                {editing && widget?.has_auth && (
                  <label className="flex items-center gap-1.5 text-[11px] text-muted-foreground mt-1 cursor-pointer">
                    <input type="checkbox" checked={clearSecret} onChange={(e) => setClearSecret(e.target.checked)} />
                    Remove the stored key
                  </label>
                )}
              </div>
            )}

            {/* Render kind */}
            <div>
              <label className="text-xs text-muted-foreground block mb-1">Render as</label>
              <div className="flex items-center gap-0.5 p-0.5 rounded bg-muted/50 border border-border w-fit">
                {(["template", "custom"] as const).map((k) => (
                  <button key={k} onClick={() => setRenderKind(k)}
                    className={`px-2.5 py-1 text-[11px] rounded capitalize transition-colors ${renderKind === k ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}>
                    {k === "template" ? "Template" : "Custom HTML/JS"}
                  </button>
                ))}
              </div>
            </div>

            {renderKind === "template" ? (
              <>
                <div>
                  <label className="text-xs text-muted-foreground block mb-1">Template</label>
                  <select value={templateType} onChange={(e) => setTemplateType(e.target.value as WidgetTemplateType)} className={input}>
                    {(Object.keys(TEMPLATE_LABELS) as WidgetTemplateType[]).map((t) => <option key={t} value={t}>{TEMPLATE_LABELS[t]}</option>)}
                  </select>
                </div>
                <div className="space-y-2">
                  {fields.map((f) => (
                    <div key={f.key}>
                      <label className="text-[11px] text-muted-foreground block mb-0.5">{f.label}{f.hint ? ` — ${f.hint}` : ""}</label>
                      <input value={bindings[f.key] || ""} onChange={(e) => setBindings((b) => ({ ...b, [f.key]: e.target.value }))} className={input} />
                    </div>
                  ))}
                  <p className="text-[11px] text-muted-foreground">Map each field to a path in the response (e.g. <code>main.temp</code>). Plain text with no matching path is used literally.</p>
                </div>
              </>
            ) : (
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Custom HTML / JS (sandboxed)</label>
                <textarea value={customHtml} onChange={(e) => setCustomHtml(e.target.value)} rows={10}
                  className={`${input} font-mono text-[12px]`} spellCheck={false} />
                <p className="text-[11px] text-muted-foreground mt-1">
                  Runs in an isolated sandbox with no access to Nurby&apos;s login or cameras. The fetched data
                  arrives as the <code>nurbydata</code> event (and <code>window.nurbyData</code>).
                </p>
              </div>
            )}
          </div>

          {/* Right: preview */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">Preview</span>
              <button onClick={runTest} disabled={testing || !url.trim()}
                className="text-[11px] px-2 py-1 rounded border border-border text-foreground hover:bg-muted/50 disabled:opacity-50">
                {testing ? "Testing…" : "Test fetch"}
              </button>
            </div>
            <div className="h-48 rounded-lg border border-border bg-background overflow-hidden">
              {testData?.ok ? (
                <WidgetView widget={draftWidget} data={testData.data} />
              ) : testData ? (
                <div className="w-full h-full flex flex-col items-center justify-center gap-1 px-3 text-center">
                  <span className="text-xs text-rose-300">Fetch failed</span>
                  <span className="text-[10px] text-muted-foreground break-words">{testData.error}</span>
                </div>
              ) : (
                <div className="w-full h-full flex items-center justify-center text-xs text-muted-foreground">Run a test fetch to preview</div>
              )}
            </div>
            {testData?.ok && (
              <details className="text-[11px]">
                <summary className="text-muted-foreground cursor-pointer">Raw response</summary>
                <pre className="mt-1 max-h-32 overflow-auto scrollbar-thin bg-background border border-border rounded p-2 text-[10px] text-muted-foreground">{JSON.stringify(testData.data, null, 2)}</pre>
              </details>
            )}
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-border sticky bottom-0 bg-card">
          <button onClick={onClose} className="text-xs px-3 py-1.5 rounded border border-border text-muted-foreground hover:text-foreground">Cancel</button>
          <button onClick={save} disabled={saving}
            className="text-xs px-3 py-1.5 rounded bg-accent text-accent-foreground font-medium hover:opacity-90 disabled:opacity-50">
            {saving ? "Saving…" : editing ? "Save changes" : "Create widget"}
          </button>
        </div>
      </div>
    </div>
  );
}
