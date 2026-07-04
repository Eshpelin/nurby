"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";

// Settings card for registered device instances (Device table). Rules
// fire these via the {type: "device", device_id} action; this card is
// where they get created, tested, and deleted.

// Shape served by GET /api/devices (preset catalog).
interface DevicePreset {
  id: string;
  name: string;
  category: string;
  platform: string;
  summary: string;
  default_port: number;
  webhook_action: {
    type: string;
    url: string;
    payload_template?: Record<string, unknown>;
  };
}

// Shape served by GET /api/devices/instances.
interface DeviceInstance {
  id: string;
  name: string;
  preset_id: string | null;
  endpoint_url: string;
  has_secret: boolean;
  payload_template: Record<string, unknown> | null;
  timeout_seconds: number;
  enabled: boolean;
  last_test_at: string | null;
  last_test_ok: boolean | null;
  last_error: string | null;
  created_at: string;
}

const CUSTOM = "custom";

// FastAPI errors come back as {detail: string} or {detail: [{msg, loc}...]}.
function detailToMessage(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        const item = d as { msg?: string; loc?: unknown[] };
        const loc = Array.isArray(item.loc) ? item.loc.slice(1).join(".") : "";
        return loc ? `${loc}: ${item.msg || "invalid"}` : item.msg || "invalid";
      })
      .join("; ");
  }
  return "Request failed";
}

export function DevicesSection() {
  const { authFetch } = useAuth();
  const [show, setShow] = useState(false);

  const [instances, setInstances] = useState<DeviceInstance[]>([]);
  const [presets, setPresets] = useState<DevicePreset[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");

  // Add form
  const [showAdd, setShowAdd] = useState(false);
  const [formPresetId, setFormPresetId] = useState<string>(CUSTOM);
  const [formName, setFormName] = useState("");
  const [formIp, setFormIp] = useState("");
  const [formPort, setFormPort] = useState("");
  const [formSecret, setFormSecret] = useState("");
  const [formUrl, setFormUrl] = useState("");
  const [formError, setFormError] = useState("");
  const [saving, setSaving] = useState(false);

  // Per-row activity
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, { ok: boolean; detail: string }>>({});
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError("");
    try {
      const [instRes, presetRes] = await Promise.all([
        authFetch("/api/devices/instances"),
        authFetch("/api/devices"),
      ]);
      if (!instRes.ok) throw new Error(String(instRes.status));
      setInstances(await instRes.json());
      if (presetRes.ok) setPresets(await presetRes.json());
    } catch {
      setLoadError("Could not load devices.");
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  useEffect(() => {
    load();
  }, [load]);

  const selectedPreset = presets.find((p) => p.id === formPresetId) || null;

  const pickPreset = (id: string) => {
    setFormPresetId(id);
    setFormError("");
    const preset = presets.find((p) => p.id === id);
    if (preset) {
      setFormPort(String(preset.default_port));
      if (!formName.trim()) setFormName(preset.name);
    }
  };

  const resetForm = () => {
    setFormPresetId(CUSTOM);
    setFormName("");
    setFormIp("");
    setFormPort("");
    setFormSecret("");
    setFormUrl("");
    setFormError("");
  };

  const builtUrl = selectedPreset
    ? selectedPreset.webhook_action.url
        .replace("{ip}", formIp.trim() || "DEVICE_IP")
        .replace("{port}", formPort.trim() || String(selectedPreset.default_port))
    : formUrl.trim();

  const save = async () => {
    setFormError("");
    if (!formName.trim()) {
      setFormError("Name is required.");
      return;
    }
    if (selectedPreset && !formIp.trim()) {
      setFormError("Device IP is required.");
      return;
    }
    if (!selectedPreset && !formUrl.trim()) {
      setFormError("Endpoint URL is required.");
      return;
    }
    const body: Record<string, unknown> = {
      name: formName.trim(),
      endpoint_url: builtUrl,
    };
    if (selectedPreset) body.preset_id = selectedPreset.id;
    if (formSecret.trim()) body.secret = formSecret.trim();
    setSaving(true);
    try {
      const res = await authFetch("/api/devices/instances", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setFormError(detailToMessage(data?.detail));
        return;
      }
      resetForm();
      setShowAdd(false);
      await load();
    } catch {
      setFormError("Could not reach the server.");
    } finally {
      setSaving(false);
    }
  };

  const toggleEnabled = async (device: DeviceInstance) => {
    setBusyId(device.id);
    try {
      const res = await authFetch(`/api/devices/instances/${device.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !device.enabled }),
      });
      if (res.ok) {
        const updated: DeviceInstance = await res.json();
        setInstances((prev) => prev.map((d) => (d.id === updated.id ? updated : d)));
      }
    } catch {
      /* leave list as-is */
    } finally {
      setBusyId(null);
    }
  };

  const testDevice = async (device: DeviceInstance) => {
    setTestingId(device.id);
    try {
      const res = await authFetch(`/api/devices/instances/${device.id}/test`, {
        method: "POST",
      });
      if (res.ok) {
        const result: { ok: boolean; detail: string } = await res.json();
        setTestResults((prev) => ({ ...prev, [device.id]: result }));
      } else {
        const data = await res.json().catch(() => null);
        setTestResults((prev) => ({
          ...prev,
          [device.id]: { ok: false, detail: detailToMessage(data?.detail) },
        }));
      }
      await load();
    } catch {
      setTestResults((prev) => ({
        ...prev,
        [device.id]: { ok: false, detail: "Could not reach the server." },
      }));
    } finally {
      setTestingId(null);
    }
  };

  const deleteDevice = async (device: DeviceInstance) => {
    if (!window.confirm(`Delete device "${device.name}"? Rules that fire it will start failing.`)) return;
    setBusyId(device.id);
    try {
      const res = await authFetch(`/api/devices/instances/${device.id}`, { method: "DELETE" });
      if (res.ok || res.status === 204) {
        setInstances((prev) => prev.filter((d) => d.id !== device.id));
      }
    } catch {
      /* leave list as-is */
    } finally {
      setBusyId(null);
    }
  };

  const presetName = (id: string | null) =>
    id ? presets.find((p) => p.id === id)?.name || null : null;

  const statusDot = (d: DeviceInstance) => {
    if (d.last_test_ok === true) return <span className="w-2 h-2 rounded-full flex-shrink-0 bg-green-500" title="Last test passed" />;
    if (d.last_test_ok === false) return <span className="w-2 h-2 rounded-full flex-shrink-0 bg-red-500" title={d.last_error || "Last test failed"} />;
    return <span className="w-2 h-2 rounded-full flex-shrink-0 bg-muted-foreground/40" title="Never tested" />;
  };

  return (
    <div className="rounded-lg border border-border bg-card">
      <button
        onClick={() => setShow(!show)}
        className="w-full px-4 py-3.5 flex items-center justify-between text-left"
      >
        <div className="flex items-center gap-3">
          <span className="w-2.5 h-2.5 rounded-full flex-shrink-0 bg-muted-foreground/40" />
          <div>
            <div className="text-sm font-medium">Devices</div>
            <div className="text-xs text-muted-foreground mt-0.5">
              Physical alarms, relays and speakers rules can trigger
            </div>
          </div>
        </div>
        <svg
          width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
          className={`text-muted-foreground transition-transform ${show ? "rotate-180" : ""}`}
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>

      {show && (
        <div className="px-4 pb-4 border-t border-border pt-3 space-y-3">
          {loadError && <p className="text-xs text-red-400">{loadError}</p>}
          {loading && !loadError && (
            <p className="text-xs text-muted-foreground">Loading.</p>
          )}

          {!loading && !loadError && instances.length === 0 && (
            <p className="text-xs text-muted-foreground">
              No devices yet. Register a buzzer, relay, or speaker and rules can fire it.
            </p>
          )}

          {instances.map((d) => {
            const preset = presetName(d.preset_id);
            const result = testResults[d.id];
            return (
              <div key={d.id} className="rounded-md border border-border bg-background p-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2 min-w-0">
                    {statusDot(d)}
                    <span className="font-medium text-sm truncate">{d.name}</span>
                    {preset && (
                      <span className="text-[11px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground flex-shrink-0">
                        {preset}
                      </span>
                    )}
                    {!d.enabled && (
                      <span className="text-[11px] px-1.5 py-0.5 rounded border border-border text-muted-foreground flex-shrink-0">
                        disabled
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-1.5 flex-shrink-0">
                    <button
                      onClick={() => toggleEnabled(d)}
                      disabled={busyId === d.id}
                      className="text-xs px-2 py-1 rounded border border-border hover:bg-muted text-muted-foreground disabled:opacity-50"
                    >
                      {d.enabled ? "Disable" : "Enable"}
                    </button>
                    <button
                      onClick={() => testDevice(d)}
                      disabled={testingId === d.id}
                      className="text-xs px-2 py-1 rounded border border-border hover:bg-muted text-muted-foreground disabled:opacity-50"
                    >
                      {testingId === d.id ? "Testing." : "Test"}
                    </button>
                    <button
                      onClick={() => deleteDevice(d)}
                      disabled={busyId === d.id}
                      className="text-xs px-2 py-1 rounded border border-red-800 text-red-400 hover:bg-red-900/30 disabled:opacity-50"
                    >
                      Delete
                    </button>
                  </div>
                </div>
                <div className="text-[11px] text-muted-foreground font-mono truncate mt-1.5">
                  {d.endpoint_url}
                </div>
                {result && (
                  <div className={`text-[11px] mt-1.5 ${result.ok ? "text-green-400" : "text-red-400"}`}>
                    {result.ok ? "Test passed." : "Test failed."} {result.detail}
                  </div>
                )}
              </div>
            );
          })}

          {!showAdd ? (
            <button
              onClick={() => setShowAdd(true)}
              className="px-2 py-1 text-xs rounded border border-dashed border-border hover:bg-muted text-muted-foreground"
            >
              + Add device
            </button>
          ) : (
            <div className="rounded-md border border-border bg-background p-3 space-y-3">
              <div className="text-xs font-medium">Add device</div>
              <div>
                <label className="text-[11px] text-muted-foreground block mb-1">Device type</label>
                <select
                  value={formPresetId}
                  onChange={(e) => pickPreset(e.target.value)}
                  className="w-full px-2 py-1.5 rounded-md bg-background border border-border text-xs"
                >
                  <option value={CUSTOM}>Custom endpoint</option>
                  {presets.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
                {selectedPreset && (
                  <p className="text-[10px] text-muted-foreground mt-1">{selectedPreset.summary}</p>
                )}
              </div>
              <div>
                <label className="text-[11px] text-muted-foreground block mb-1">Name</label>
                <input
                  type="text"
                  value={formName}
                  onChange={(e) => setFormName(e.target.value)}
                  placeholder="Garage buzzer"
                  className="w-full px-2 py-1.5 rounded-md bg-background border border-border text-xs"
                />
              </div>
              {selectedPreset ? (
                <div className="grid grid-cols-3 gap-2">
                  <div className="col-span-2">
                    <label className="text-[11px] text-muted-foreground block mb-1">Device IP</label>
                    <input
                      type="text"
                      value={formIp}
                      onChange={(e) => setFormIp(e.target.value)}
                      placeholder="192.168.1.50"
                      className="w-full px-2 py-1.5 rounded-md bg-background border border-border text-xs font-mono"
                    />
                  </div>
                  <div>
                    <label className="text-[11px] text-muted-foreground block mb-1">Port</label>
                    <input
                      type="text"
                      value={formPort}
                      onChange={(e) => setFormPort(e.target.value)}
                      className="w-full px-2 py-1.5 rounded-md bg-background border border-border text-xs font-mono"
                    />
                  </div>
                </div>
              ) : (
                <div>
                  <label className="text-[11px] text-muted-foreground block mb-1">Endpoint URL</label>
                  <input
                    type="text"
                    value={formUrl}
                    onChange={(e) => setFormUrl(e.target.value)}
                    placeholder="http://192.168.1.50:8090/alert"
                    className="w-full px-2 py-1.5 rounded-md bg-background border border-border text-xs font-mono"
                  />
                </div>
              )}
              <div>
                <label className="text-[11px] text-muted-foreground block mb-1">
                  Signing secret (optional)
                </label>
                <input
                  type="password"
                  value={formSecret}
                  onChange={(e) => setFormSecret(e.target.value)}
                  placeholder="Same value configured on the device"
                  className="w-full px-2 py-1.5 rounded-md bg-background border border-border text-xs font-mono"
                />
              </div>
              {selectedPreset && (
                <div className="text-[10px] text-muted-foreground font-mono truncate">
                  → {builtUrl}
                </div>
              )}
              {formError && <p className="text-[11px] text-red-400">{formError}</p>}
              <div className="flex items-center gap-2">
                <button
                  onClick={save}
                  disabled={saving}
                  className="px-3 py-1.5 text-xs rounded-md bg-foreground text-background font-medium hover:opacity-90 disabled:opacity-50"
                >
                  {saving ? "Saving." : "Save device"}
                </button>
                <button
                  onClick={() => {
                    resetForm();
                    setShowAdd(false);
                  }}
                  className="px-3 py-1.5 text-xs rounded-md border border-border hover:bg-muted text-muted-foreground"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default DevicesSection;
