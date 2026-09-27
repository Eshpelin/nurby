"use client";

// Settings card for the MQTT / Home Assistant integration
// (docs/integrations/mqtt.md). Off by default: flipping it on starts the
// bridge in the API process, which publishes Nurby's topic tree plus HA
// discovery configs to the broker. Admin-only writes, mirroring the other
// settings cards.

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";

interface MqttStatus {
  enabled: boolean;
  host: string;
  port: number;
  discovery_enabled: boolean;
  connected: boolean;
  last_error: string | null;
  last_connected_at: number | null;
  announced_entities: number;
}

export default function MqttSection() {
  const { authFetch, user } = useAuth();
  const isAdmin = user?.role === "admin";

  const [enabled, setEnabled] = useState(false);
  const [host, setHost] = useState("");
  const [port, setPort] = useState("1883");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [topicPrefix, setTopicPrefix] = useState("nurby");
  const [savedTopicPrefix, setSavedTopicPrefix] = useState("nurby");
  const [tls, setTls] = useState(false);
  const [discovery, setDiscovery] = useState(true);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<MqttStatus | null>(null);
  const [testResult, setTestResult] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await authFetch("/api/system/settings");
      if (res.ok) {
        const d = await res.json();
        if (typeof d.mqtt_enabled === "boolean") setEnabled(d.mqtt_enabled);
        if (typeof d.mqtt_host === "string") setHost(d.mqtt_host || "");
        if (d.mqtt_port) setPort(String(d.mqtt_port));
        if (typeof d.mqtt_username === "string") setUsername(d.mqtt_username || "");
        if (typeof d.mqtt_tls === "boolean") setTls(d.mqtt_tls);
        if (typeof d.mqtt_discovery_enabled === "boolean") setDiscovery(d.mqtt_discovery_enabled);
        if (typeof d.mqtt_topic_prefix === "string") {
          setTopicPrefix(d.mqtt_topic_prefix || "nurby");
          setSavedTopicPrefix(d.mqtt_topic_prefix || "nurby");
        }
      }
      const s = await authFetch("/api/integrations/mqtt");
      if (s.ok) setStatus(await s.json());
    } catch {
      /* ignore */
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  useEffect(() => {
    load();
  }, [load]);

  const patch = useCallback(
    async (body: Record<string, unknown>) => {
      setSaving(true);
      try {
        const res = await authFetch("/api/system/settings", {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!res.ok) {
          const d = await res.json().catch(() => null);
          setTestResult(d?.detail ? `Save failed: ${d.detail}` : "Save failed");
        }
      } finally {
        setSaving(false);
      }
    },
    [authFetch],
  );

  const refreshStatus = useCallback(async () => {
    try {
      const s = await authFetch("/api/integrations/mqtt");
      if (s.ok) setStatus(await s.json());
    } catch {
      /* ignore */
    }
  }, [authFetch]);

  useEffect(() => {
    if (!enabled) return;
    const timer = window.setInterval(refreshStatus, 15000);
    return () => window.clearInterval(timer);
  }, [enabled, refreshStatus]);

  const toggle = async () => {
    const next = !enabled;
    setEnabled(next);
    await patch({ mqtt_enabled: next });
    setTimeout(refreshStatus, 1500);
  };

  const save = async () => {
    const body: Record<string, unknown> = {
      mqtt_host: host.trim(),
      mqtt_port: Number(port) || 1883,
      mqtt_username: username.trim(),
      mqtt_tls: tls,
      mqtt_discovery_enabled: discovery,
      mqtt_topic_prefix: topicPrefix.trim() || "nurby",
    };
    // Write-only: only PATCH when the user typed a new one (empty = keep).
    if (password) body.mqtt_password = password;
    await patch(body);
    setSavedTopicPrefix(topicPrefix.trim() || "nurby");
    setPassword("");
    setTestResult("Saved");
    setTimeout(refreshStatus, 1500);
  };

  const test = async () => {
    setTestResult(null);
    try {
      const res = await authFetch("/api/integrations/mqtt/test", { method: "POST" });
      const d = await res.json().catch(() => null);
      if (!res.ok) {
        setTestResult(d?.detail || "Test failed");
        return;
      }
      setTestResult(d?.ok ? d.detail : `Failed: ${d?.detail || "unknown error"}`);
    } catch {
      setTestResult("Test failed");
    }
    refreshStatus();
  };

  if (loading) return null;

  const statusLine = status?.connected
    ? `Connected${status.announced_entities ? ` · ${status.announced_entities} HA entities announced` : ""}`
    : status?.last_error
      ? `Not connected · ${status.last_error}`
      : enabled
        ? "Connecting…"
        : null;

  return (
    <div className="rounded-lg border border-border bg-card px-4 py-3.5 space-y-3">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-sm font-medium mb-1">MQTT / Home Assistant</div>
          <p className="text-xs text-muted-foreground">
            Publish cameras, events, and snapshots to an MQTT broker. Home
            Assistant discovers Nurby automatically — motion sensors,
            detections, camera tiles, and control switches, no YAML.
          </p>
        </div>
        <button
          type="button"
          disabled={!isAdmin || saving}
          onClick={toggle}
          aria-label={enabled ? "Disable MQTT" : "Enable MQTT"}
          className={`relative w-10 h-5 rounded-full transition-colors flex-shrink-0 ${enabled ? "bg-accent" : "bg-muted"} ${saving || !isAdmin ? "opacity-50" : ""}`}
        >
          <span
            className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-all ${enabled ? "left-[1.375rem]" : "left-0.5"}`}
          />
        </button>
      </div>

      {enabled && (
        <div className="space-y-2 border-t border-border pt-3">
          <div className="flex items-center gap-2">
            <label className="text-xs text-muted-foreground w-20">Broker host</label>
            <input
              value={host}
              disabled={!isAdmin}
              onChange={(e) => setHost(e.target.value)}
              placeholder="mosquitto or 192.168.1.20"
              className="flex-1 text-xs font-mono bg-background border border-border rounded px-2 py-1"
            />
          </div>
          <div className="flex items-center gap-2">
            <label className="text-xs text-muted-foreground w-20">Topic prefix</label>
            <input
              value={topicPrefix}
              disabled={!isAdmin}
              onChange={(e) => setTopicPrefix(e.target.value)}
              className="flex-1 text-xs font-mono bg-background border border-border rounded px-2 py-1"
              placeholder="nurby"
            />
          </div>
          {topicPrefix.trim() !== savedTopicPrefix && (
            <p className="text-[11px] text-amber-300">
              Changing this prefix leaves retained MQTT topics under “{savedTopicPrefix}/” on the broker. Clean those topics up separately if you no longer need them.
            </p>
          )}
          <div className="flex items-center gap-2">
            <label className="text-xs text-muted-foreground w-20">Port</label>
            <input
              value={port}
              disabled={!isAdmin}
              onChange={(e) => setPort(e.target.value.replace(/[^0-9]/g, ""))}
              className="w-20 text-xs font-mono bg-background border border-border rounded px-2 py-1"
            />
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground ml-2">
              <input
                type="checkbox"
                checked={tls}
                disabled={!isAdmin}
                onChange={(e) => setTls(e.target.checked)}
              />
              TLS
            </label>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-xs text-muted-foreground w-20">Username</label>
            <input
              value={username}
              disabled={!isAdmin}
              onChange={(e) => setUsername(e.target.value)}
              className="flex-1 text-xs font-mono bg-background border border-border rounded px-2 py-1"
            />
          </div>
          <div className="flex items-center gap-2">
            <label className="text-xs text-muted-foreground w-20">Password</label>
            <input
              type="password"
              value={password}
              disabled={!isAdmin}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={status ? "•••••••• (saved)" : "optional"}
              className="flex-1 text-xs font-mono bg-background border border-border rounded px-2 py-1"
            />
          </div>
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={discovery}
              disabled={!isAdmin}
              onChange={(e) => setDiscovery(e.target.checked)}
            />
            Announce devices to Home Assistant (discovery)
          </label>

          <div className="flex items-center gap-2 pt-1">
            <button
              type="button"
              disabled={!isAdmin || saving}
              onClick={save}
              className="px-3 py-1.5 text-xs rounded-md border border-border hover:bg-muted transition-colors disabled:opacity-50"
            >
              {saving ? "Saving…" : "Save"}
            </button>
            <button
              type="button"
              disabled={!isAdmin || saving}
              onClick={test}
              className="px-3 py-1.5 text-xs rounded-md border border-border hover:bg-muted transition-colors disabled:opacity-50"
            >
              Test connection
            </button>
          </div>

          {testResult && <p className="text-[11px] text-muted-foreground">{testResult}</p>}
          {statusLine && (
            <p
              className={`text-[11px] ${status?.connected ? "text-emerald-400" : "text-amber-300"}`}
            >
              {statusLine}
            </p>
          )}
          {status?.last_connected_at && (
            <p className="text-[11px] text-muted-foreground">
              Last connected {new Date(status.last_connected_at * 1000).toLocaleString()}
            </p>
          )}
          {!host.trim() && (
            <p className="text-[11px] text-muted-foreground">
              No broker yet?{" "}
              <code className="bg-background px-1 rounded">
                docker compose --profile mqtt up -d
              </code>{" "}
              starts a bundled Mosquitto; use host{" "}
              <code className="bg-background px-1 rounded">mosquitto</code>.
            </p>
          )}
          {!isAdmin && (
            <p className="text-[10px] text-muted-foreground">Only an admin can change these.</p>
          )}
        </div>
      )}
    </div>
  );
}
