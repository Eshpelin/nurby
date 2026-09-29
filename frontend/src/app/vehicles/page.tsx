"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { EmptyState, CameraGlyph } from "@/components/EmptyState";
import { useToast, useConfirm } from "@/lib/feedback";
import { timeAgo as timeAgoBase } from "@/lib/time";
import { AssociationSummary } from "@/components/review/AssociationSummary";
import { translate } from "@/lib/i18n";

interface Vehicle {
  id: string;
  display_name: string;
  nickname: string | null;
  license_plate: string | null;
  vehicle_type: string | null;
  make: string | null;
  model: string | null;
  color: string | null;
  description: string | null;
  description_status: string;
  is_starred: boolean;
  is_provisional: boolean;
  sighting_count: number;
  first_seen_at: string | null;
  last_seen_at: string | null;
}

interface VehicleSummary {
  vehicle_id: string;
  display_name: string;
  license_plate: string | null;
  vehicle_type: string | null;
  color: string | null;
  make: string | null;
  model: string | null;
  description: string | null;
  is_starred: boolean;
  total_sightings: number;
  sightings_1h: number;
  sightings_24h: number;
  last_seen_at: string | null;
  last_seen_camera: string | null;
  first_seen_at: string | null;
}

interface VehicleActivity {
  observation_id: string;
  camera_id: string;
  camera_name: string | null;
  started_at: string;
  vlm_description: string | null;
  thumbnail_path: string | null;
  plate_text: string | null;
  plate_confidence: number | null;
  plate_source: string | null;
  vehicle_confidence: number | null;
  identity_kind: "plate" | "appearance";
}

const timeAgo = (iso: string | null) => timeAgoBase(iso, { fallback: "never" });

const TYPE_ICON: Record<string, string> = {
  car: "🚗", truck: "🚚", bus: "🚌", motorcycle: "🏍️", van: "🚐", forklift: "🚜",
};

export default function VehiclesPage() {
  const { authFetch, token, user } = useAuth();
  const t = useCallback(
    (key: string, values?: Record<string, string | number>) => translate(user?.locale, key, values),
    [user?.locale],
  );
  const toast = useToast();
  const confirm = useConfirm();
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [summaries, setSummaries] = useState<Record<string, VehicleSummary>>({});
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [activity, setActivity] = useState<Record<string, VehicleActivity[]>>({});
  const [editing, setEditing] = useState<Vehicle | null>(null);

  const fetchAll = useCallback(async () => {
    try {
      const [vRes, sRes] = await Promise.all([
        authFetch("/api/vehicles"),
        authFetch("/api/vehicles/activity/summary"),
      ]);
      if (vRes.ok) setVehicles(await vRes.json());
      if (sRes.ok) {
        const arr: VehicleSummary[] = await sRes.json();
        const map: Record<string, VehicleSummary> = {};
        for (const s of arr) map[s.vehicle_id] = s;
        setSummaries(map);
      }
    } catch {/* ignore */}
    finally { setLoading(false); }
  }, [authFetch]);

  useEffect(() => {
    fetchAll();
    const i = setInterval(fetchAll, 30000);
    return () => clearInterval(i);
  }, [fetchAll]);

  const toggle = useCallback(async (id: string) => {
    if (expanded === id) { setExpanded(null); return; }
    setExpanded(id);
    if (!activity[id]) {
      try {
        const r = await authFetch(`/api/vehicles/activity/${id}?limit=50`);
        if (r.ok) { const data = await r.json(); setActivity((p) => ({ ...p, [id]: data })); }
      } catch {/* ignore */}
    }
  }, [expanded, activity, authFetch]);

  const toggleStar = useCallback(async (v: Vehicle) => {
    setVehicles((prev) => prev.map((x) => x.id === v.id ? { ...x, is_starred: !x.is_starred } : x));
    try {
      await authFetch(`/api/vehicles/${v.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_starred: !v.is_starred }),
      });
    } catch { fetchAll(); }
  }, [authFetch, fetchAll]);

  const remove = useCallback(async (id: string) => {
    const ok = await confirm({
      title: t("vehicles.delete_title"),
      body: t("vehicles.delete_body"),
      danger: true,
    });
    if (!ok) return;
    setVehicles((prev) => prev.filter((x) => x.id !== id));
    try {
      const res = await authFetch(`/api/vehicles/${id}`, { method: "DELETE" });
      if (!res.ok && res.status !== 204) throw new Error();
      toast.success(t("vehicles.deleted"));
    } catch {
      toast.error(t("vehicles.delete_failed"));
      fetchAll();
    }
  }, [authFetch, fetchAll, confirm, toast, t]);

  if (loading) {
    return <div className="px-6 py-8 text-sm text-muted-foreground">{t("vehicles.loading")}</div>;
  }

  if (vehicles.length === 0) {
    return (
      <div className="px-6 py-16 max-w-xl mx-auto">
        <EmptyState
          icon={<CameraGlyph />}
          title={t("vehicles.empty_title")}
          body={t("vehicles.empty_body")}
          actionLabel={t("vehicles.go_to_cameras")}
          actionHref="/"
        />
      </div>
    );
  }

  return (
    <div className="px-6 py-6 max-w-4xl mx-auto">
      <div className="mb-5">
        <h1 className="text-2xl font-semibold tracking-tight">{t("vehicles.title")}</h1>
        <p className="text-sm text-muted-foreground mt-0.5">
          {t("vehicles.subtitle")}
        </p>
      </div>

      <div className="space-y-2.5">
        {vehicles.map((v) => {
          const s = summaries[v.id];
          const isOpen = expanded === v.id;
          return (
            <div key={v.id} className="rounded-lg border border-border bg-card overflow-hidden">
              <div className="flex items-center gap-3 p-3">
                <button onClick={() => toggle(v.id)} className="flex items-center gap-3 flex-1 min-w-0 text-left">
                  <div className="relative w-14 h-14 rounded-md bg-muted overflow-hidden flex-shrink-0 flex items-center justify-center">
                    <img
                      src={`/api/vehicles/${v.id}/photo${token ? `?token=${token}` : ""}`}
                      alt={v.display_name}
                      className="w-full h-full object-cover"
                      onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                    />
                    <span className="absolute text-xl pointer-events-none">{TYPE_ICON[v.vehicle_type || ""] || "🚗"}</span>
                  </div>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-sm truncate">{v.nickname || v.display_name}</span>
                      {v.license_plate && (
                        <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-accent/15 text-accent border border-accent/30">
                          {v.license_plate}
                        </span>
                      )}
                      {v.is_provisional && (
                        <span className="text-[9px] uppercase tracking-wide text-muted-foreground">{t("vehicles.auto")}</span>
                      )}
                    </div>
                    {v.description && (
                      <div className="text-[11px] text-muted-foreground truncate mt-0.5">{v.description}</div>
                    )}
                    <div className="text-[11px] text-muted-foreground mt-0.5">
                      {s ? (
                        <>{t("vehicles.last_seen", { time: timeAgo(s.last_seen_at) })}{s.last_seen_camera ? ` ${t("vehicles.on_camera", { camera: s.last_seen_camera })}` : ""}</>
                      ) : (
                        <>{t("vehicles.last_seen", { time: timeAgo(v.last_seen_at) })}</>
                      )}
                    </div>
                  </div>
                </button>
                <div className="flex items-center gap-2 flex-shrink-0">
                  {s && (
                    <div className="hidden sm:flex flex-col items-end text-[10px] font-mono text-muted-foreground">
                      <span className="text-accent">{t("vehicles.sightings_hour", { count: s.sightings_1h })}</span>
                      <span>{t("vehicles.sightings_total", { count: s.total_sightings })}</span>
                    </div>
                  )}
                  <button onClick={() => toggleStar(v)} title={t("vehicles.star")} className={`text-base ${v.is_starred ? "text-yellow-400" : "text-muted-foreground hover:text-foreground"}`}>
                    {v.is_starred ? "★" : "☆"}
                  </button>
                  <Link
                    href={`/memory?entity_kind=vehicle&entity_key=${v.id}`}
                    title={t("vehicles.notes_title")}
                    className="text-muted-foreground hover:text-foreground text-xs"
                  >
                    {t("vehicles.notes")}
                  </Link>
                  <button onClick={() => setEditing(v)} title={t("vehicles.edit")} className="text-muted-foreground hover:text-foreground text-xs">{t("vehicles.edit")}</button>
                </div>
              </div>

              {isOpen && (
                <div className="border-t border-border bg-background/40 p-3">
                  <AssociationSummary objectKind="vehicle" objectKey={v.id} />
                  <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-2">
                    {t("vehicles.sightings_newest")}
                  </div>
                  {!activity[v.id] ? (
                    <div className="text-[11px] text-muted-foreground">{t("vehicles.loading_sightings")}</div>
                  ) : activity[v.id].length === 0 ? (
                    <div className="text-[11px] text-muted-foreground">{t("vehicles.no_sightings")}</div>
                  ) : (
                    <div className="space-y-1.5">
                      {activity[v.id].map((a) => (
                        <Link
                          key={a.observation_id}
                          href={`/cameras/${a.camera_id}`}
                          className="flex items-center gap-2.5 rounded-md border border-border bg-card/50 p-1.5 hover:border-accent/50 transition-colors"
                        >
                          <div className="w-16 h-10 rounded bg-muted overflow-hidden flex-shrink-0">
                            {a.thumbnail_path && (
                              <img src={`/api/observations/${a.observation_id}/thumbnail${token ? `?token=${token}` : ""}`} alt="" className="w-full h-full object-cover" />
                            )}
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="text-[11px] truncate">{a.vlm_description || t("vehicles.vehicle_seen")}</div>
                            <div className="text-[10px] text-muted-foreground">
                              {a.camera_name || t("vehicles.camera")} · {timeAgo(a.started_at)}
                              {a.plate_text ? (
                                <> · {t("vehicles.plate", { plate: a.plate_text })}{a.plate_confidence != null ? ` (${Math.round(a.plate_confidence * 100)}% ${a.plate_source || t("vehicles.ocr")})` : ""}</>
                              ) : (
                                <> · {t("vehicles.appearance_only")}</>
                              )}
                            </div>
                          </div>
                        </Link>
                      ))}
                    </div>
                  )}
                  <button onClick={() => remove(v.id)} className="mt-3 text-[11px] text-red-400 hover:text-red-300">
                    {t("vehicles.delete")}
                  </button>
                  <MergeVehicleControl
                    source={v}
                    targets={vehicles.filter((candidate) => candidate.id !== v.id)}
                    onMerged={() => { setExpanded(null); fetchAll(); }}
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>

      {editing && (
        <EditModal vehicle={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); fetchAll(); }} />
      )}
    </div>
  );
}

function MergeVehicleControl({
  source,
  targets,
  onMerged,
}: {
  source: Vehicle;
  targets: Vehicle[];
  onMerged: () => void;
}) {
  const { authFetch } = useAuth();
  const { user } = useAuth();
  const t = (key: string, values?: Record<string, string | number>) => translate(user?.locale, key, values);
  const toast = useToast();
  const confirm = useConfirm();
  const [targetId, setTargetId] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  if (targets.length === 0) return null;

  const merge = async () => {
    if (!targetId) return;
    const target = targets.find((item) => item.id === targetId);
    if (!target) return;
    const ok = await confirm({
      title: t("vehicles.merge_title"),
      body: t("vehicles.merge_body", { source: source.nickname || source.display_name, target: target.nickname || target.display_name }),
      danger: true,
    });
    if (!ok) return;
    setBusy(true);
    try {
      const response = await authFetch(`/api/vehicles/${targetId}/merge`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_id: source.id, note: note.trim() || null }),
      });
      if (!response.ok) {
        throw new Error(response.status === 403 ? t("vehicles.merge_admin_only") : t("vehicles.merge_failed"));
      }
      toast.success(t("vehicles.merge_success"));
      onMerged();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("vehicles.merge_error"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-3 rounded-md border border-border/70 bg-card/50 p-2">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">{t("vehicles.duplicate_identity")}</div>
      <p className="mt-1 text-[11px] text-muted-foreground">
        {t("vehicles.duplicate_help")}
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <select
          value={targetId}
          onChange={(event) => setTargetId(event.target.value)}
          disabled={busy}
          aria-label={t("vehicles.merge_aria", { vehicle: source.display_name })}
          className="min-w-44 rounded border border-border bg-background px-2 py-1 text-[11px]"
        >
          <option value="">{t("vehicles.select_surviving")}</option>
          {targets.map((target) => (
            <option key={target.id} value={target.id}>
              {target.nickname || target.display_name}{target.license_plate ? ` · ${target.license_plate}` : ""}
            </option>
          ))}
        </select>
        <input
          value={note}
          onChange={(event) => setNote(event.target.value)}
          disabled={busy}
          maxLength={500}
          placeholder={t("vehicles.optional_reason")}
          aria-label={t("vehicles.merge_reason")}
          className="min-w-44 flex-1 rounded border border-border bg-background px-2 py-1 text-[11px]"
        />
        <button
          type="button"
          onClick={() => void merge()}
          disabled={!targetId || busy}
          className="rounded border border-amber-500/40 px-2 py-1 text-[11px] text-amber-300 hover:bg-amber-500/10 disabled:opacity-40"
        >
          {busy ? t("vehicles.merging") : t("vehicles.merge_duplicate")}
        </button>
      </div>
    </div>
  );
}

function EditModal({ vehicle, onClose, onSaved }: { vehicle: Vehicle; onClose: () => void; onSaved: () => void }) {
  const { authFetch } = useAuth();
  const { user } = useAuth();
  const t = (key: string) => translate(user?.locale, key);
  const [name, setName] = useState(vehicle.display_name);
  const [plate, setPlate] = useState(vehicle.license_plate || "");
  const [make, setMake] = useState(vehicle.make || "");
  const [model, setModel] = useState(vehicle.model || "");
  const [color, setColor] = useState(vehicle.color || "");
  const [saving, setSaving] = useState(false);
  const ref = useRef<HTMLInputElement | null>(null);
  useEffect(() => { ref.current?.focus(); }, []);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await authFetch(`/api/vehicles/${vehicle.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          display_name: name.trim() || vehicle.display_name,
          license_plate: plate.trim() || null,
          make: make.trim() || null,
          model: model.trim() || null,
          color: color.trim() || null,
        }),
      });
      onSaved();
    } finally { setSaving(false); }
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm p-4" onClick={onClose}>
      <form onClick={(e) => e.stopPropagation()} onSubmit={save} className="w-full max-w-sm rounded-lg border border-border bg-card-elevated p-5 space-y-3">
        <h2 className="text-sm font-semibold">{t("vehicles.edit_title")}</h2>
        {[
          [t("vehicles.name"), name, setName, ref] as const,
          [t("vehicles.license_plate"), plate, setPlate, undefined] as const,
          [t("vehicles.make"), make, setMake, undefined] as const,
          [t("vehicles.model"), model, setModel, undefined] as const,
          [t("vehicles.color"), color, setColor, undefined] as const,
        ].map(([label, val, set, r]) => (
          <div key={label}>
            <label className="block text-[11px] text-muted-foreground mb-1">{label}</label>
            <input
              ref={r as React.RefObject<HTMLInputElement> | undefined}
              value={val}
              onChange={(e) => set(e.target.value)}
              className="w-full px-3 py-2 text-sm rounded-md border border-border bg-background focus:border-accent/60 focus:outline-none"
            />
          </div>
        ))}
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} className="px-3 py-1.5 text-xs rounded-md border border-border text-muted-foreground hover:text-foreground">{t("vehicles.cancel")}</button>
          <button type="submit" disabled={saving} className="px-4 py-1.5 text-xs font-medium rounded-md bg-accent text-accent-foreground hover:opacity-90 disabled:opacity-50">
            {saving ? t("vehicles.saving") : t("vehicles.save")}
          </button>
        </div>
      </form>
    </div>
  );
}
