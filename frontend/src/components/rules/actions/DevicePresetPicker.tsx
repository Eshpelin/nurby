"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import type { WebhookDraft } from "../types";

// Shape served by GET /api/devices.
interface DevicePreset {
  id: string;
  name: string;
  category: string;
  platform: string;
  summary: string;
  hardware: string[];
  wiring: string;
  receiver: string;
  default_port: number;
  supports_hmac: boolean;
  webhook_action: {
    type: string;
    url: string;
    secret?: string;
    payload_template?: Record<string, unknown>;
    timeout?: number;
  };
  steps: string[];
}

export interface DevicePresetPickerProps {
  onApply: (patch: Partial<WebhookDraft>) => void;
}

export function DevicePresetPicker({ onApply }: DevicePresetPickerProps) {
  const { authFetch } = useAuth();
  const [open, setOpen] = useState(false);
  const [presets, setPresets] = useState<DevicePreset[] | null>(null);
  const [loadError, setLoadError] = useState("");
  const [selectedId, setSelectedId] = useState<string>("");
  const [ip, setIp] = useState("");

  useEffect(() => {
    if (!open || presets) return;
    authFetch("/api/devices")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((data: DevicePreset[]) => setPresets(data))
      .catch(() => setLoadError("Could not load device presets."));
  }, [open, presets, authFetch]);

  const selected = presets?.find((p) => p.id === selectedId) || null;

  const apply = () => {
    if (!selected) return;
    const port = selected.default_port;
    const url = selected.webhook_action.url
      .replace("{ip}", ip.trim() || "DEVICE_IP")
      .replace("{port}", String(port));
    const tpl = selected.webhook_action.payload_template;
    onApply({
      url,
      useCustomPayload: !!tpl,
      payloadTemplate: tpl ? JSON.stringify(tpl, null, 2) : "",
      payloadError: "",
    });
    setOpen(false);
  };

  return (
    <div className="rounded-md border border-dashed border-border">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-3 py-2 text-xs text-muted-foreground hover:bg-muted/50 rounded-md"
      >
        <span>📟 Start from a physical device preset</span>
        <span>{open ? "▾" : "▸"}</span>
      </button>

      {open && (
        <div className="px-3 pb-3 pt-1 space-y-3">
          {loadError && <div className="text-[11px] text-red-400">{loadError}</div>}
          {!presets && !loadError && (
            <div className="text-[11px] text-muted-foreground">Loading devices.</div>
          )}

          {presets && (
            <div className="flex flex-wrap gap-1.5">
              {presets.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => setSelectedId(p.id)}
                  className={`px-2 py-1 text-[11px] rounded border transition-colors ${
                    selectedId === p.id
                      ? "border-accent bg-accent/10 text-accent"
                      : "border-border hover:bg-muted text-muted-foreground"
                  }`}
                  title={p.summary}
                >
                  {p.name}
                </button>
              ))}
            </div>
          )}

          {selected && (
            <div className="space-y-2 rounded-md border border-border bg-background/50 p-2.5">
              <div className="text-[11px] text-muted-foreground">{selected.summary}</div>
              <div className="text-[10px] text-muted-foreground">
                <span className="font-medium text-zinc-300">Wiring.</span> {selected.wiring}
              </div>
              <ol className="text-[10px] text-muted-foreground list-decimal pl-4 space-y-0.5">
                {selected.steps.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ol>
              <a
                href={`/api/devices/${selected.id}/receiver`}
                target="_blank"
                rel="noreferrer"
                className="inline-block text-[10px] text-accent hover:underline"
              >
                View receiver script ({selected.receiver.split("/").pop()})
              </a>
              <div className="flex items-end gap-2 pt-1">
                <div className="flex-1">
                  <label className="text-[10px] text-muted-foreground block mb-1">
                    Device IP on your network
                  </label>
                  <input
                    type="text"
                    value={ip}
                    onChange={(e) => setIp(e.target.value)}
                    placeholder="192.168.1.50"
                    className="w-full px-2 py-1.5 rounded-md bg-background border border-border text-xs font-mono"
                  />
                </div>
                <button
                  type="button"
                  onClick={apply}
                  className="px-3 py-1.5 text-xs rounded-md bg-foreground text-background font-medium hover:opacity-90"
                >
                  Use this device
                </button>
              </div>
              {selected.supports_hmac && (
                <p className="text-[10px] text-muted-foreground">
                  Set a signing secret below and the same value on the device so it only
                  reacts to signed Nurby alerts.
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default DevicePresetPicker;
