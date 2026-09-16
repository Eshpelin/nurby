"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/lib/feedback";

type AccessMode = "all" | "selected" | "none";
interface AdminUser {
  id: string;
  email: string;
  display_name: string | null;
  role: string;
  is_active: boolean;
  camera_access_mode: AccessMode;
}
interface Camera { id: string; name: string; location_label: string | null }

export default function CameraAccessPage() {
  const { user, authFetch } = useAuth();
  const toast = useToast();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<AdminUser | null>(null);
  const [grants, setGrants] = useState<Set<string> | null>(null);
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    if (user?.role !== "admin") return;
    let cancelled = false;
    Promise.all([authFetch("/api/users"), authFetch("/api/cameras")])
      .then(async ([u, c]) => {
        if (!u.ok || !c.ok) throw new Error("Could not load users and cameras.");
        const [rows, cams] = await Promise.all([u.json(), c.json()]);
        if (!cancelled) { setUsers(rows); setCameras(cams); }
      })
      .catch(() => { if (!cancelled) setError("Could not load users and cameras. Refresh to try again."); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [authFetch, user?.role]);

  const readAccess = useCallback(async (id: string) => {
    const [u, g] = await Promise.all([
      authFetch(`/api/users/${id}`), authFetch(`/api/users/${id}/cameras`),
    ]);
    if (!u.ok || !g.ok) throw new Error("Could not load camera access.");
    const [account, rows]: [AdminUser, Camera[]] = await Promise.all([u.json(), g.json()]);
    return { account, ids: new Set(rows.map((c) => c.id)) };
  }, [authFetch]);

  useEffect(() => {
    setSelected(null); setGrants(null); setError(null);
    if (!selectedId) return;
    let cancelled = false;
    readAccess(selectedId).then(({ account, ids }) => {
      if (!cancelled) { setSelected(account); setGrants(ids); }
    }).catch(() => {
      if (!cancelled) setError("Could not load camera access. Select the user again to retry.");
    });
    return () => { cancelled = true; };
  }, [selectedId, readAccess, retry]);

  const change = async (path: string, method: string, body?: object) => {
    if (!selected || busy) return;
    setBusy(true);
    try {
      const res = await authFetch(path, {
        method,
        ...(body ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => null);
        throw new Error(typeof detail?.detail === "string" ? detail.detail : "Could not update access.");
      }
      const { account, ids } = await readAccess(selected.id);
      setSelected(account); setGrants(ids);
      setUsers((rows) => rows.map((u) => u.id === account.id ? account : u));
      toast.success("Camera access updated.");
    } catch (e) {
      // Do not display a stale policy as authoritative after an uncertain write.
      setSelected(null); setGrants(null);
      setError("Reload this user's access before making another change.");
      toast.error(e instanceof Error ? e.message : "Could not update access.");
    } finally { setBusy(false); }
  };

  if (user && user.role !== "admin") return <div className="p-8">Only an admin can manage camera access.</div>;
  if (loading) return <div className="p-8 text-muted-foreground">Loading…</div>;
  const mode = selected?.camera_access_mode ?? "none";
  const summary = !selected?.is_active ? "Account deactivated. Cannot sign in." : mode === "all"
    ? `Can see all ${cameras.length} cameras, including cameras added later.`
    : mode === "none" || grants?.size === 0 ? "Cannot see any cameras."
    : `Can see ${grants?.size} of ${cameras.length} cameras.`;

  return (
    <div className="max-w-4xl mx-auto p-6">
      <Link href="/settings" className="text-sm text-muted-foreground">← Settings</Link>
      <h1 className="text-2xl font-semibold mt-3 mb-2">Camera access</h1>
      <p className="text-sm text-muted-foreground mb-6">
        Choose all cameras, selected cameras, or no cameras for each user.
        Removing the last selected camera leaves no access. Admins always see every camera.
        Guardian views also require their separate dependant grants.
      </p>
      {error && <p role="alert" className="text-sm text-red-400 mb-4">{error}</p>}
      <div className="grid gap-6 md:grid-cols-[minmax(0,18rem)_1fr]">
        <section aria-label="Users" className="space-y-2">
          {users.filter((u) => u.role !== "admin").map((u) => (
            <button key={u.id} disabled={busy} onClick={() => {
              if (selectedId === u.id) setRetry((n) => n + 1);
              else setSelectedId(u.id);
            }} className={`w-full text-left rounded-md border px-3 py-3 ${selectedId === u.id ? "border-accent bg-accent/10" : "border-border"}`}>
              <span className="block text-sm font-medium">{u.display_name || u.email}</span>
              <span className="text-xs text-muted-foreground">{u.role}{!u.is_active && " · deactivated"}</span>
            </button>
          ))}
          {users.every((u) => u.role === "admin") && <p className="text-sm text-muted-foreground">No non-admin users yet. Invite a viewer from Settings.</p>}
        </section>
        <section aria-label="Camera permissions">
          {!selected || grants === null ? <p className="text-sm text-muted-foreground">{selectedId && !error ? "Loading access…" : "Select a user to view their access."}</p> : <>
            <h2 className="font-medium">{selected.display_name || selected.email}</h2>
            <p role="status" className="text-sm text-muted-foreground mt-1 mb-4">{summary}</p>
            <label className="block text-sm mb-4">Access
              <select aria-label="Camera access mode" value={mode} disabled={busy}
                onChange={(e) => change(`/api/users/${selected.id}`, "PATCH", { camera_access_mode: e.target.value })}
                className="block mt-1 rounded border border-border bg-card p-2 w-full">
                <option value="none">No cameras</option>
                <option value="selected">Selected cameras</option>
                <option value="all">All cameras, including future cameras</option>
              </select>
            </label>
            {mode === "selected" && <div className="space-y-2">
              {cameras.length === 0 && <p className="text-sm text-muted-foreground">No cameras configured yet.</p>}
              {cameras.map((c) => <label key={c.id} className="flex items-center gap-3 rounded border border-border p-3 text-sm">
                <input type="checkbox" checked={grants.has(c.id)} disabled={busy}
                  onChange={() => change(`/api/users/${selected.id}/cameras/${c.id}`, grants.has(c.id) ? "DELETE" : "POST")} />
                <span>{c.name}{c.location_label && <span className="block text-xs text-muted-foreground">{c.location_label}</span>}</span>
              </label>)}
            </div>}
          </>}
        </section>
      </div>
    </div>
  );
}
