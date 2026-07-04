"use client";

import { type DeviceDraft, type DeviceOption } from "../types";
import { StyledSelect } from "../StyledSelect";

export interface DeviceEditorProps {
  draft: DeviceDraft;
  devices: DeviceOption[];
  onChange: (patch: Partial<DeviceDraft>) => void;
}

export function DeviceEditor({ draft, devices, onChange }: DeviceEditorProps) {
  const d = draft;

  const setExtras = (text: string) => {
    let error = "";
    if (text.trim()) {
      try {
        const parsed = JSON.parse(text);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
          error = "Extras must be a JSON object";
        }
      } catch {
        error = "Extras is not valid JSON";
      }
    }
    onChange({ extrasJson: text, extrasError: error });
  };

  return (
    <div className="space-y-3">
      <div className="text-[11px] text-muted-foreground bg-muted/50 rounded px-2 py-1.5">
        Fire a device registered in Settings → Devices. Nurby signs and
        delivers the request server-side using the stored endpoint and secret.
      </div>
      <div>
        <label className="text-xs text-muted-foreground block mb-1">Device</label>
        {devices.length === 0 ? (
          <div className="text-[11px] text-muted-foreground border border-dashed border-border rounded-md px-3 py-2">
            No devices registered yet. Add one under Settings → Devices.
          </div>
        ) : (
          <StyledSelect
            value={d.device_id}
            options={devices.map((dev) => ({ value: dev.id, label: dev.name }))}
            onChange={(v) => onChange({ device_id: v })}
            placeholder="Pick a device."
          />
        )}
      </div>
      <div>
        <label className="text-xs text-muted-foreground block mb-1">
          Extra payload fields (optional JSON)
        </label>
        <textarea
          value={d.extrasJson}
          onChange={(e) => setExtras(e.target.value)}
          rows={3}
          className="w-full px-3 py-2 rounded-md bg-background border border-border text-xs font-mono resize-y"
          placeholder='{"pattern": "sos"}'
        />
        {d.extrasError && (
          <div className="text-[11px] text-red-400 mt-1">{d.extrasError}</div>
        )}
      </div>
    </div>
  );
}

export default DeviceEditor;
