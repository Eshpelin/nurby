"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/lib/feedback";

// Per-user camera access control (issue #40). Admin-only surface that mirrors
// the existing /guardian/admin and /ask/admin gated pages. It drives the
// UserCameraAccess admin CRUD endpoints under /api/users/{id}/cameras.
//
// Policy reminder (see shared/camera_access.py): a non-admin user with ZERO
// grants falls through to ALL cameras (the single-owner no-op). Granting the
// first camera flips that user into allowlist mode. The UI makes that switch
// explicit so an admin is never surprised.

interface AdminUser {
  id: string;
  email: string;
  display_name: string | null;
  role: string;
  is_active: boolean;
}

interface Camera {
  id: string;
  name: string;
  location_label: string | null;
}

export default function CameraAccessPage() {
  const { user, authFetch } = useAuth();
  const toast = useToast();

  const [users, setUsers] = useState<AdminUser[]>([]);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [loading, setLoading] = useState(true);

  const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
  // camera ids the selected user is granted. null = not loaded yet.
  const [grantedIds, setGrantedIds] = useState<Set<string> | null>(null);
  const [grantsLoading, setGrantsLoading] = useState(false);
  // camera ids with an in-flight grant/revoke, so we can disable the row.
  const [pending, setPending] = useState<Set<string>>(new Set());

  const refresh = useCallback(async () => {
    try {
      const [uRes, cRes] = await Promise.all([
        authFetch("/api/users"),
        authFetch("/api/cameras"),
      ]);
      if (uRes.ok) setUsers(await uRes.json());
      if (cRes.ok) {
        const list: Camera[] = await cRes.json();
        setCameras(
          list.map((c) => ({
            id: c.id,
            name: c.name,
            location_label: c.location_label ?? null,
          }))
        );
      }
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const loadGrants = useCallback(
    async (userId: string) => {
      setGrantsLoading(true);
      setGrantedIds(null);
      try {
        const res = await authFetch(`/api/users/${userId}/cameras`);
        if (res.ok) {
          const list: { id: string }[] = await res.json();
          setGrantedIds(new Set(list.map((c) => c.id)));
        } else {
          setGrantedIds(new Set());
          toast.error("Could not load this user's camera access.");
        }
      } catch {
        setGrantedIds(new Set());
        toast.error("Network error loading camera access.");
      } finally {
        setGrantsLoading(false);
      }
    },
    [authFetch, toast]
  );

  const selectUser = (u: AdminUser) => {
    setSelectedUserId(u.id);
    loadGrants(u.id);
  };

  const selectedUser = useMemo(
    () => users.find((u) => u.id === selectedUserId) ?? null,
    [users, selectedUserId]
  );

  const setPendingFor = (cameraId: string, on: boolean) => {
    setPending((prev) => {
      const next = new Set(prev);
      if (on) next.add(cameraId);
      else next.delete(cameraId);
      return next;
    });
  };

  const toggleCamera = async (cameraId: string, grant: boolean) => {
    if (!selectedUserId) return;
    setPendingFor(cameraId, true);
    try {
      const res = await authFetch(
        `/api/users/${selectedUserId}/cameras/${cameraId}`,
        { method: grant ? "POST" : "DELETE" }
      );
      // POST returns 201, DELETE returns 204. Treat a 409 ("already has
      // access") on grant and a 404 on revoke as already-in-the-target-state
      // so the UI stays consistent with the server instead of erroring.
      const ok =
        res.ok ||
        (grant && res.status === 409) ||
        (!grant && res.status === 404);
      if (ok) {
        setGrantedIds((prev) => {
          const next = new Set(prev ?? []);
          if (grant) next.add(cameraId);
          else next.delete(cameraId);
          return next;
        });
      } else {
        const body = await res.json().catch(() => null);
        toast.error(
          (body && typeof body.detail === "string" && body.detail) ||
            `Could not ${grant ? "grant" : "revoke"} access (${res.status}).`
        );
      }
    } catch {
      toast.error("Network error updating camera access.");
    } finally {
      setPendingFor(cameraId, false);
    }
  };

  // Admin gate, mirroring /guardian/admin and /ask/admin.
  if (user && user.role !== "admin") {
    return (
      <div className="p-8 text-muted-foreground">
        Only an admin can manage per-user camera access.
      </div>
    );
  }
  if (loading) return <div className="p-8 text-muted-foreground">Loading...</div>;

  // Admins always see every camera, so there is nothing to assign for them.
  const assignableUsers = users.filter((u) => u.role !== "admin");
  const grantedCount = grantedIds ? grantedIds.size : 0;
  const inAllowlistMode = grantedIds !== null && grantedCount > 0;

  return (
    <div className="max-w-4xl mx-auto p-6">
      <Link
        href="/settings"
        className="text-sm text-muted-foreground hover:text-foreground"
      >
        ← Settings
      </Link>
      <h1 className="text-2xl font-semibold tracking-tight mt-3 mb-1">
        Camera access
      </h1>
      <p className="text-sm text-muted-foreground mb-6 max-w-2xl">
        Grant or revoke specific cameras for each non-admin user. Admins always
        see every camera, so they are not listed here.
      </p>

      {/* The no-op policy made explicit, so granting the first camera is never
          a surprise. */}
      <div className="mb-6 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-xs text-amber-200/90 leading-relaxed">
        <strong className="text-amber-200">How access works.</strong> A user
        with <strong>zero</strong> grants currently sees{" "}
        <strong>all cameras</strong> (the default for single-owner setups).
        Granting their first camera switches that user into{" "}
        <strong>allowlist mode</strong>: from then on they see only the cameras
        you grant. Revoking their last grant returns them to seeing all cameras.
      </div>

      {assignableUsers.length === 0 ? (
        <div className="rounded-lg border border-border bg-card p-8 text-center text-sm text-muted-foreground">
          No non-admin users yet. Invite a viewer or guardian from{" "}
          <Link href="/settings" className="text-accent hover:underline">
            Settings → Invite Keys
          </Link>{" "}
          to manage their camera access here.
        </div>
      ) : (
        <div className="grid gap-6 md:grid-cols-[minmax(0,18rem)_1fr]">
          {/* User list */}
          <section>
            <h2 className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">
              Users
            </h2>
            <div className="space-y-1.5">
              {assignableUsers.map((u) => {
                const active = u.id === selectedUserId;
                return (
                  <button
                    key={u.id}
                    onClick={() => selectUser(u)}
                    className={`w-full text-left rounded-md border px-3 py-2.5 transition-colors ${
                      active
                        ? "border-accent/50 bg-accent/10"
                        : "border-border bg-card hover:border-muted-foreground/30"
                    } ${u.is_active ? "" : "opacity-60"}`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium truncate">
                        {u.display_name || u.email}
                      </span>
                      <span className="text-[10px] uppercase tracking-wider text-muted-foreground flex-shrink-0">
                        {u.role}
                      </span>
                    </div>
                    {u.display_name && (
                      <div className="text-[11px] text-muted-foreground truncate">
                        {u.email}
                      </div>
                    )}
                    {!u.is_active && (
                      <div className="text-[10px] text-muted-foreground mt-0.5">
                        deactivated
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          </section>

          {/* Camera grants for the selected user */}
          <section>
            {!selectedUser ? (
              <div className="rounded-lg border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
                Select a user to view and edit which cameras they can access.
              </div>
            ) : (
              <>
                <div className="flex items-start justify-between gap-3 mb-3">
                  <div className="min-w-0">
                    <h2 className="text-sm font-medium truncate">
                      {selectedUser.display_name || selectedUser.email}
                    </h2>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {grantsLoading
                        ? "Loading access…"
                        : inAllowlistMode
                          ? `Allowlist mode · ${grantedCount} of ${cameras.length} camera${
                              cameras.length === 1 ? "" : "s"
                            } granted`
                          : "No grants · this user currently sees all cameras"}
                    </p>
                  </div>
                  {!grantsLoading && (
                    <span
                      className={`flex-shrink-0 text-[10px] font-medium uppercase tracking-wider rounded px-1.5 py-0.5 border ${
                        inAllowlistMode
                          ? "border-accent/40 bg-accent/10 text-accent"
                          : "border-amber-500/40 bg-amber-500/10 text-amber-300"
                      }`}
                    >
                      {inAllowlistMode ? "Allowlist" : "All cameras"}
                    </span>
                  )}
                </div>

                {cameras.length === 0 ? (
                  <div className="rounded-lg border border-border bg-card p-8 text-center text-sm text-muted-foreground">
                    No cameras configured yet.
                  </div>
                ) : grantsLoading || grantedIds === null ? (
                  <div className="rounded-lg border border-border bg-card p-8 text-center text-sm text-muted-foreground">
                    Loading access…
                  </div>
                ) : (
                  <div className="space-y-1.5">
                    {cameras.map((cam) => {
                      const granted = grantedIds.has(cam.id);
                      const busy = pending.has(cam.id);
                      // Granting the first camera is the moment that flips the
                      // user into allowlist mode. Call it out on that row.
                      const isFirstGrant = !inAllowlistMode && !granted;
                      return (
                        <div
                          key={cam.id}
                          className="flex items-center gap-3 rounded-md border border-border bg-card px-3 py-2.5"
                        >
                          <div className="flex-1 min-w-0">
                            <div className="text-sm font-medium truncate">
                              {cam.name}
                            </div>
                            {cam.location_label && (
                              <div className="text-[11px] text-muted-foreground truncate">
                                {cam.location_label}
                              </div>
                            )}
                          </div>
                          {granted && (
                            <span className="text-[10px] uppercase tracking-wider text-accent flex-shrink-0">
                              granted
                            </span>
                          )}
                          {isFirstGrant && (
                            <span
                              className="text-[10px] text-amber-300/80 flex-shrink-0 hidden sm:inline"
                              title="Granting this enables allowlist mode for this user"
                            >
                              enables allowlist
                            </span>
                          )}
                          <button
                            onClick={() => {
                              // Revoking the LAST grant doesn't restrict
                              // this user further — it flips them back to
                              // seeing every camera (see the policy note
                              // above). That's the opposite of what
                              // "revoke" usually means, so confirm before
                              // doing it.
                              if (granted && grantedCount === 1) {
                                const ok = window.confirm(
                                  `${cam.name} is ${selectedUser.display_name || selectedUser.email}'s only granted camera. Revoking it will NOT lock them out — with zero grants they'll see all ${cameras.length} cameras instead. Continue?`
                                );
                                if (!ok) return;
                              }
                              toggleCamera(cam.id, !granted);
                            }}
                            disabled={busy}
                            aria-pressed={granted}
                            aria-label={
                              granted
                                ? `Revoke ${cam.name}`
                                : `Grant ${cam.name}`
                            }
                            className={`relative w-10 h-5 rounded-full transition-colors flex-shrink-0 ${
                              granted ? "bg-accent" : "bg-muted"
                            } ${busy ? "opacity-50" : ""}`}
                          >
                            <span
                              className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-all ${
                                granted ? "left-[1.375rem]" : "left-0.5"
                              }`}
                            />
                          </button>
                        </div>
                      );
                    })}
                  </div>
                )}
              </>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
