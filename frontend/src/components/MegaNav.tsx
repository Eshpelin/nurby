"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";

/* ────────────────────────────────────────────────────────────────────────
   Mega navigation. Ten flat links collapse into four grouped triggers, each
   opening a single shared panel that morphs (position + width) between them
   while its content cross-fades. Every panel surfaces live state for its
   domain (unreviewed alerts, who was just seen, active rules) so the nav is a
   glance-able console, not just a link list.
   ──────────────────────────────────────────────────────────────────────── */

type LinkDef = { label: string; href: string; hint: string };
type MenuDef = { id: string; label: string; links: LinkDef[] };

const MENUS: MenuDef[] = [
  {
    id: "review",
    label: "Review",
    links: [
      { label: "Recordings", href: "/recordings", hint: "Browse & filter footage" },
      { label: "Timeline", href: "/timeline", hint: "Everything, in order" },
      { label: "Alerts", href: "/events", hint: "Rule-triggered events" },
    ],
  },
  {
    id: "directory",
    label: "Directory",
    links: [
      { label: "People", href: "/people", hint: "Faces & identities" },
      { label: "Vehicles", href: "/vehicles", hint: "Plates & re-ID" },
    ],
  },
  {
    id: "insights",
    label: "Insights",
    links: [
      { label: "Ask Nurby", href: "/ask", hint: "Question your footage" },
      { label: "Reports", href: "/reports", hint: "Scheduled digests" },
    ],
  },
  {
    id: "manage",
    label: "Manage",
    links: [
      { label: "Rules", href: "/rules", hint: "Automations & alerts" },
      { label: "Pipeline", href: "/pipeline", hint: "AI backlog & throughput" },
      { label: "Settings", href: "/settings", hint: "Cameras, AI, account" },
    ],
  },
];

// Panel width per menu (px). The shared card transitions between these, which
// is what gives the morph its feel; keep them distinct but not jarring.
const PANEL_WIDTH: Record<string, number> = {
  review: 560,
  directory: 600,
  insights: 480,
  manage: 460,
};

function timeAgo(iso?: string | null): string {
  if (!iso) return "";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function initials(name?: string | null): string {
  if (!name) return "?";
  return name.split(" ").map((w) => w[0]).join("").toUpperCase().slice(0, 2);
}

// "Living Room · 2m ago", or just one part, or "Not seen yet" — never a
// dangling separator.
function seenLabel(camera?: string | null, iso?: string | null): string {
  const parts = [camera, timeAgo(iso)].filter(Boolean);
  return parts.length ? parts.join(" · ") : "Not seen yet";
}

// ── shared data shapes (only the fields the panels render) ──
interface PersonSummary {
  person_id: string; display_name: string; nickname?: string | null;
  photo_path?: string | null; sightings_24h: number;
  last_seen_at?: string | null; last_seen_camera?: string | null;
}
interface VehicleSummary {
  vehicle_id: string; display_name: string; license_plate?: string | null;
  vehicle_type?: string | null; is_starred?: boolean;
  last_seen_at?: string | null; last_seen_camera?: string | null;
}
interface RuleRow { id: string; name: string; enabled: boolean; severity?: string | null }
interface EventRow {
  id: string; fired_at: string;
  payload?: { camera_id?: string; object_detections?: { objects?: { label?: string }[] } } | null;
}
interface Cam { id: string; name: string }

export interface NavData {
  cams: Record<string, string>;
  alertCount: number | null;
  recentAlerts: EventRow[];
  latestRec: { id: string; started_at: string; camera_id: string } | null;
  people: PersonSummary[];
  vehicles: VehicleSummary[];
  facesToName: number | null;
  rules: RuleRow[];
  ensureData: (id: string) => void;
  tq: string;
}

// Live nav data, lazily fetched per menu and cached, shared by the desktop
// mega-menu and the mobile accordion so neither double-fetches on its own view.
export function useNavData(): NavData {
  const { authFetch, token } = useAuth();
  const [cams, setCams] = useState<Record<string, string>>({});
  const [alertCount, setAlertCount] = useState<number | null>(null);
  const [recentAlerts, setRecentAlerts] = useState<EventRow[]>([]);
  const [latestRec, setLatestRec] = useState<{ id: string; started_at: string; camera_id: string } | null>(null);
  const [people, setPeople] = useState<PersonSummary[]>([]);
  const [vehicles, setVehicles] = useState<VehicleSummary[]>([]);
  const [facesToName, setFacesToName] = useState<number | null>(null);
  const [rules, setRules] = useState<RuleRow[]>([]);
  const fetched = useRef<Record<string, boolean>>({});

  const tq = token ? `?token=${token}` : "";

  const loadCams = useCallback(async () => {
    try {
      const r = await authFetch("/api/cameras");
      if (r.ok) {
        const list: Cam[] = await r.json();
        const m: Record<string, string> = {};
        for (const c of list) m[c.id] = c.name;
        setCams(m);
      }
    } catch { /* silent */ }
  }, [authFetch]);

  // Poll the one always-relevant number (unreviewed alerts) so the Review
  // trigger carries a live badge even before the menu is opened.
  const loadAlertCount = useCallback(async () => {
    try {
      const r = await authFetch("/api/events/count?acked=false");
      if (r.ok) { const d = await r.json(); setAlertCount(d.count ?? 0); }
    } catch { /* silent */ }
  }, [authFetch]);

  useEffect(() => {
    loadCams();
    loadAlertCount();
    const t = setInterval(loadAlertCount, 20000);
    return () => clearInterval(t);
  }, [loadCams, loadAlertCount]);

  const ensureData = useCallback(async (id: string) => {
    if (fetched.current[id]) return;
    fetched.current[id] = true;
    try {
      if (id === "review") {
        const [a, rec] = await Promise.all([
          authFetch("/api/events/history?acked=false&limit=3"),
          authFetch("/api/recordings?limit=1"),
        ]);
        if (a.ok) setRecentAlerts(await a.json());
        if (rec.ok) { const list = await rec.json(); setLatestRec(list[0] ?? null); }
      } else if (id === "directory") {
        const [p, v, s] = await Promise.all([
          authFetch("/api/persons/activity/summary"),
          authFetch("/api/vehicles/activity/summary"),
          authFetch("/api/persons/suggestions?min_sightings=2"),
        ]);
        if (p.ok) setPeople((await p.json()).slice(0, 4));
        if (v.ok) setVehicles((await v.json()).slice(0, 3));
        if (s.ok) setFacesToName((await s.json()).length);
      } else if (id === "manage") {
        const r = await authFetch("/api/rules");
        if (r.ok) setRules(await r.json());
      }
    } catch {
      fetched.current[id] = false; // allow a retry on the next open
    }
  }, [authFetch]);

  return { cams, alertCount, recentAlerts, latestRec, people, vehicles, facesToName, rules, ensureData, tq };
}

export function MegaNav() {
  const pathname = usePathname();
  const {
    cams, alertCount, recentAlerts, latestRec, people, vehicles, facesToName, rules, ensureData, tq,
  } = useNavData();

  const [active, setActive] = useState<string | null>(null);
  const [anchor, setAnchor] = useState<{ left: number; center: number }>({ left: 0, center: 0 });

  const wrapRef = useRef<HTMLDivElement | null>(null);
  const triggerRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const openTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── open / close with hover intent ──
  const measure = useCallback((id: string) => {
    const btn = triggerRefs.current[id];
    const wrap = wrapRef.current;
    if (!btn || !wrap) return;
    const b = btn.getBoundingClientRect();
    const w = wrap.getBoundingClientRect();
    setAnchor({ left: b.left - w.left, center: b.left - w.left + b.width / 2 });
  }, []);

  const openMenu = useCallback((id: string) => {
    if (closeTimer.current) { clearTimeout(closeTimer.current); closeTimer.current = null; }
    setActive(id);
    measure(id);
    ensureData(id);
  }, [measure, ensureData]);

  const scheduleClose = useCallback(() => {
    if (closeTimer.current) clearTimeout(closeTimer.current);
    closeTimer.current = setTimeout(() => setActive(null), 160);
  }, []);
  const cancelClose = useCallback(() => {
    if (closeTimer.current) { clearTimeout(closeTimer.current); closeTimer.current = null; }
  }, []);

  const onTriggerEnter = (id: string) => {
    cancelClose();
    if (active && active !== id) { openMenu(id); return; } // instant switch
    if (openTimer.current) clearTimeout(openTimer.current);
    openTimer.current = setTimeout(() => openMenu(id), 70);
  };
  const onTriggerLeave = () => {
    if (openTimer.current) { clearTimeout(openTimer.current); openTimer.current = null; }
    scheduleClose();
  };

  // Re-measure the active anchor on resize; close on route change + Escape.
  useLayoutEffect(() => { if (active) measure(active); }, [active, measure]);
  useEffect(() => { setActive(null); }, [pathname]);
  useEffect(() => {
    if (!active) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setActive(null); };
    const onResize = () => measure(active);
    window.addEventListener("keydown", onKey);
    window.addEventListener("resize", onResize);
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("resize", onResize); };
  }, [active, measure]);

  const isMenuActive = (m: MenuDef) => m.links.some((l) => pathname === l.href);
  const width = active ? PANEL_WIDTH[active] : 480;
  // Clamp the card within the wrapper so it never overflows the right edge.
  const wrapW = wrapRef.current?.getBoundingClientRect().width ?? 0;
  const left = Math.max(0, Math.min(anchor.left - 12, wrapW - width));
  const caretLeft = anchor.center - left;

  return (
    <div ref={wrapRef} className="relative hidden md:block" onMouseLeave={onTriggerLeave}>
      {/* Trigger row */}
      <nav className="flex items-center gap-1">
        <Link
          href="/"
          className={`px-3 py-1.5 rounded-md text-sm transition-colors whitespace-nowrap ${
            pathname === "/" ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground"
          }`}
        >
          Dashboard
        </Link>

        {MENUS.map((m) => {
          const on = active === m.id;
          const routeActive = isMenuActive(m);
          const showAlertBadge = m.id === "review" && (alertCount ?? 0) > 0;
          return (
            <button
              key={m.id}
              ref={(el) => { triggerRefs.current[m.id] = el; }}
              onMouseEnter={() => onTriggerEnter(m.id)}
              onFocus={() => openMenu(m.id)}
              onClick={() => (on ? setActive(null) : openMenu(m.id))}
              aria-haspopup="true"
              aria-expanded={on}
              className={`group relative flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm transition-colors whitespace-nowrap ${
                on || routeActive ? "text-foreground" : "text-muted-foreground hover:text-foreground"
              } ${on ? "bg-muted" : ""}`}
            >
              {m.label}
              {showAlertBadge && (
                <span className="min-w-[15px] h-[15px] px-1 flex items-center justify-center rounded-full bg-danger/90 text-white text-[9px] font-bold leading-none">
                  {alertCount! > 99 ? "99+" : alertCount}
                </span>
              )}
              <svg
                width="9" height="9" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2"
                className={`opacity-50 transition-transform duration-200 ${on ? "rotate-180" : ""}`}
              >
                <path d="M2.5 4.5 L6 8 L9.5 4.5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              {routeActive && !on && (
                <span className="absolute left-3 right-3 -bottom-[1px] h-[2px] rounded-full bg-accent/70" />
              )}
            </button>
          );
        })}

        <Link
          href="/guardian"
          className={`px-3 py-1.5 rounded-md text-sm transition-colors whitespace-nowrap ${
            pathname.startsWith("/guardian") ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground"
          }`}
        >
          Guardian
        </Link>
      </nav>

      {/* Shared morphing panel */}
      {active && (
        <div
          className="absolute top-full pt-2 z-50"
          style={{ left, width, transition: "left 260ms cubic-bezier(0.16,1,0.3,1), width 260ms cubic-bezier(0.16,1,0.3,1)" }}
          onMouseEnter={cancelClose}
          onMouseLeave={scheduleClose}
        >
          {/* connector caret aligned to the active trigger */}
          <span
            className="absolute -top-[1px] h-3 w-3 rotate-45 rounded-[3px] border-l border-t border-border bg-card-elevated"
            style={{ left: Math.max(14, Math.min(caretLeft - 6, width - 26)), transition: "left 260ms cubic-bezier(0.16,1,0.3,1)" }}
          />
          <div className="mega-panel relative overflow-hidden rounded-xl border border-border bg-card-elevated shadow-2xl shadow-black/50">
            {/* top accent hairline + traveling sheen */}
            <div className="absolute inset-x-0 top-0 h-px overflow-hidden">
              <div className="h-full w-full bg-gradient-to-r from-transparent via-accent/50 to-transparent" />
              <div className="mega-sheen absolute inset-y-0 w-1/3 bg-gradient-to-r from-transparent via-accent to-transparent" />
            </div>
            {/* faint console grid */}
            <div className="mega-grid pointer-events-none absolute inset-0 opacity-[0.5]" />

            <div key={active} className="relative p-3">
              {active === "review" && (
                <ReviewPanel
                  cams={cams} alertCount={alertCount} recentAlerts={recentAlerts}
                  latestRec={latestRec} tq={tq} onNavigate={() => setActive(null)}
                />
              )}
              {active === "directory" && (
                <DirectoryPanel
                  people={people} vehicles={vehicles} facesToName={facesToName}
                  tq={tq} onNavigate={() => setActive(null)}
                />
              )}
              {active === "insights" && <InsightsPanel onNavigate={() => setActive(null)} />}
              {active === "manage" && <ManagePanel rules={rules} onNavigate={() => setActive(null)} />}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── panel building blocks ─────────────────────────────────────────────── */

function PanelLinks({ links, onNavigate }: { links: LinkDef[]; onNavigate: () => void }) {
  return (
    <div className="mt-3 grid grid-cols-1 gap-1 border-t border-border-subtle pt-2">
      {links.map((l, i) => (
        <Link
          key={l.href}
          href={l.href}
          onClick={onNavigate}
          className="mega-item group flex items-center justify-between rounded-lg px-2.5 py-2 hover:bg-muted transition-colors"
          style={{ animationDelay: `${60 + i * 45}ms` }}
        >
          <span>
            <span className="block text-sm text-foreground">{l.label}</span>
            <span className="block text-[11px] text-muted-foreground">{l.hint}</span>
          </span>
          <span className="text-muted-foreground opacity-0 group-hover:opacity-100 -translate-x-1 group-hover:translate-x-0 transition-all">→</span>
        </Link>
      ))}
    </div>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <div className="text-[10px] font-mono uppercase tracking-wider text-muted-foreground/70 mb-1.5">{children}</div>;
}

function objectLabel(e: EventRow): string {
  const o = e.payload?.object_detections?.objects?.[0]?.label;
  return o ? o[0].toUpperCase() + o.slice(1) : "Motion";
}

function ReviewPanel({
  cams, alertCount, recentAlerts, latestRec, tq, onNavigate, compact,
}: {
  cams: Record<string, string>; alertCount: number | null; recentAlerts: EventRow[];
  latestRec: { id: string; started_at: string; camera_id: string } | null;
  tq: string; onNavigate: () => void; compact?: boolean;
}) {
  return (
    <div className={`grid gap-3 ${compact ? "grid-cols-1" : "grid-cols-[1.35fr_1fr]"}`}>
      <div>
        <SectionLabel>Needs review</SectionLabel>
        <Link
          href="/events"
          onClick={onNavigate}
          className="mega-item block rounded-lg border border-border bg-card p-3 hover:border-accent/50 transition-colors"
          style={{ animationDelay: "40ms" }}
        >
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-semibold tabular-nums">{alertCount ?? "—"}</span>
            <span className="text-xs text-muted-foreground">unreviewed alert{alertCount === 1 ? "" : "s"}</span>
            {(alertCount ?? 0) > 0 && <span className="ml-auto w-2 h-2 rounded-full bg-danger pulse-dot" />}
          </div>
          <ul className="mt-2 space-y-1">
            {recentAlerts.length === 0 && <li className="text-[11px] text-muted-foreground">All caught up.</li>}
            {recentAlerts.map((e, i) => (
              <li key={e.id} className="mega-item flex items-center gap-2 text-[11px]" style={{ animationDelay: `${120 + i * 50}ms` }}>
                <span className="w-1 h-1 rounded-full bg-accent shrink-0" />
                <span className="text-foreground truncate">{objectLabel(e)}</span>
                <span className="text-muted-foreground truncate">{cams[e.payload?.camera_id ?? ""] || "camera"}</span>
                <span className="ml-auto font-mono text-muted-foreground/70 shrink-0">{timeAgo(e.fired_at)}</span>
              </li>
            ))}
          </ul>
        </Link>
      </div>

      <div>
        <SectionLabel>Latest footage</SectionLabel>
        <Link
          href="/recordings"
          onClick={onNavigate}
          className="mega-item group block rounded-lg border border-border bg-card overflow-hidden hover:border-accent/50 transition-colors"
          style={{ animationDelay: "90ms" }}
        >
          <div className="camera-feed relative h-20 w-full">
            {latestRec && (
              <img
                src={`/api/recordings/${latestRec.id}/thumbnail${tq}`}
                alt=""
                className="h-full w-full object-cover opacity-90 group-hover:opacity-100 transition-opacity"
                onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
              />
            )}
            <div className="scanline absolute inset-0" />
            <span className="absolute top-1.5 left-1.5 flex items-center gap-1 text-[9px] font-mono text-white/80">
              <span className="w-1.5 h-1.5 rounded-full bg-danger pulse-dot" /> REC
            </span>
          </div>
          <div className="px-2.5 py-1.5">
            <div className="text-[11px] text-foreground truncate">
              {latestRec ? (cams[latestRec.camera_id] || "Camera") : "No recordings yet"}
            </div>
            {latestRec && <div className="text-[10px] font-mono text-muted-foreground">{timeAgo(latestRec.started_at)}</div>}
          </div>
        </Link>
      </div>

      <div className="col-span-2">
        <PanelLinks links={MENUS[0].links} onNavigate={onNavigate} />
      </div>
    </div>
  );
}

function Avatar({ src, name }: { src: string; name: string }) {
  const [failed, setFailed] = useState(false);
  if (failed || !src) {
    return (
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-muted text-[10px] font-medium text-muted-foreground">
        {initials(name)}
      </span>
    );
  }
  return <img src={src} alt="" onError={() => setFailed(true)} className="h-8 w-8 shrink-0 rounded-full object-cover bg-muted" />;
}

function DirectoryPanel({
  people, vehicles, facesToName, tq, onNavigate, compact,
}: {
  people: PersonSummary[]; vehicles: VehicleSummary[]; facesToName: number | null;
  tq: string; onNavigate: () => void; compact?: boolean;
}) {
  return (
    <div>
      {facesToName != null && facesToName > 0 && (
        <Link
          href="/people"
          onClick={onNavigate}
          className="mega-item mb-2 flex items-center gap-2 rounded-lg border border-accent/40 bg-accent/10 px-3 py-1.5 text-xs text-accent hover:bg-accent/15 transition-colors"
          style={{ animationDelay: "30ms" }}
        >
          <span className="w-1.5 h-1.5 rounded-full bg-accent pulse-dot" />
          {facesToName} new face{facesToName === 1 ? "" : "s"} waiting to be named
          <span className="ml-auto">→</span>
        </Link>
      )}
      <div className={`grid gap-3 ${compact ? "grid-cols-1" : "grid-cols-2"}`}>
        <div>
          <SectionLabel>Recently seen</SectionLabel>
          <div className="space-y-1">
            {people.length === 0 && <div className="text-[11px] text-muted-foreground px-1">No one yet.</div>}
            {people.map((p, i) => (
              <Link
                key={p.person_id}
                href="/people"
                onClick={onNavigate}
                className="mega-item flex items-center gap-2 rounded-lg px-1.5 py-1 hover:bg-muted transition-colors"
                style={{ animationDelay: `${60 + i * 45}ms` }}
              >
                <Avatar src={p.photo_path ? `/api/persons/${p.person_id}/photo${tq}` : ""} name={p.display_name} />
                <span className="min-w-0">
                  <span className="block text-xs text-foreground truncate">{p.nickname || p.display_name}</span>
                  <span className="block text-[10px] text-muted-foreground truncate">
                    {seenLabel(p.last_seen_camera, p.last_seen_at)}
                  </span>
                </span>
              </Link>
            ))}
          </div>
        </div>
        <div>
          <SectionLabel>Recent vehicles</SectionLabel>
          <div className="space-y-1">
            {vehicles.length === 0 && <div className="text-[11px] text-muted-foreground px-1">None yet.</div>}
            {vehicles.map((v, i) => (
              <Link
                key={v.vehicle_id}
                href="/vehicles"
                onClick={onNavigate}
                className="mega-item flex items-center gap-2 rounded-lg px-1.5 py-1 hover:bg-muted transition-colors"
                style={{ animationDelay: `${60 + i * 45}ms` }}
              >
                <span className="flex h-8 w-11 shrink-0 items-center justify-center rounded bg-muted text-sm">🚗</span>
                <span className="min-w-0">
                  <span className="flex items-center gap-1">
                    {v.license_plate ? (
                      <span className="font-mono text-[10px] px-1 py-0.5 rounded bg-amber-500/15 text-amber-300 border border-amber-500/30">{v.license_plate}</span>
                    ) : (
                      <span className="text-xs text-foreground truncate">{v.display_name}</span>
                    )}
                    {v.is_starred && <span className="text-amber-300 text-[10px]">★</span>}
                  </span>
                  <span className="block text-[10px] text-muted-foreground truncate">
                    {seenLabel(v.last_seen_camera, v.last_seen_at)}
                  </span>
                </span>
              </Link>
            ))}
          </div>
        </div>
      </div>
      <PanelLinks links={MENUS[1].links} onNavigate={onNavigate} />
    </div>
  );
}

const QUICK_ASKS = [
  "Who came to the door today?",
  "Any unfamiliar vehicles this week?",
  "Summarize last night",
];

function InsightsPanel({ onNavigate }: { onNavigate: () => void }) {
  return (
    <div>
      <SectionLabel>Ask Nurby</SectionLabel>
      <Link
        href="/ask"
        onClick={onNavigate}
        className="mega-item flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2.5 text-sm text-muted-foreground hover:border-accent/50 transition-colors"
        style={{ animationDelay: "40ms" }}
      >
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-accent">
          <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        Ask anything about your footage…
      </Link>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {QUICK_ASKS.map((q, i) => (
          <Link
            key={q}
            href={`/ask?q=${encodeURIComponent(q)}`}
            onClick={onNavigate}
            className="mega-item rounded-full border border-border-subtle px-2.5 py-1 text-[11px] text-muted-foreground hover:text-foreground hover:border-accent/40 transition-colors"
            style={{ animationDelay: `${90 + i * 45}ms` }}
          >
            {q}
          </Link>
        ))}
      </div>
      <PanelLinks links={MENUS[2].links} onNavigate={onNavigate} />
    </div>
  );
}

function ManagePanel({ rules, onNavigate }: { rules: RuleRow[]; onNavigate: () => void }) {
  const active = rules.filter((r) => r.enabled).length;
  return (
    <div>
      <SectionLabel>Automations</SectionLabel>
      <Link
        href="/rules"
        onClick={onNavigate}
        className="mega-item block rounded-lg border border-border bg-card p-2.5 hover:border-accent/50 transition-colors"
        style={{ animationDelay: "40ms" }}
      >
        <div className="flex items-baseline gap-2">
          <span className="text-2xl font-semibold tabular-nums">{active}</span>
          <span className="text-xs text-muted-foreground">rule{active === 1 ? "" : "s"} active</span>
          {rules.length > active && <span className="ml-auto text-[10px] text-muted-foreground">{rules.length - active} off</span>}
        </div>
        <ul className="mt-1.5 space-y-1">
          {rules.slice(0, 3).map((r, i) => (
            <li key={r.id} className="mega-item flex items-center gap-2 text-[11px]" style={{ animationDelay: `${110 + i * 45}ms` }}>
              <span className={`w-1.5 h-1.5 rounded-full ${r.enabled ? "bg-accent" : "bg-muted-foreground/40"}`} />
              <span className="text-foreground truncate">{r.name}</span>
              {r.severity === "alert" && <span className="ml-auto text-[9px] font-mono uppercase text-danger/80">alert</span>}
            </li>
          ))}
          {rules.length === 0 && <li className="text-[11px] text-muted-foreground">No rules yet.</li>}
        </ul>
      </Link>
      <PanelLinks links={MENUS[3].links} onNavigate={onNavigate} />
    </div>
  );
}

// Render a menu's panel by id, compact, for the mobile accordion.
function PanelFor({ id, nav, onNavigate }: { id: string; nav: NavData; onNavigate: () => void }) {
  if (id === "review") {
    return (
      <ReviewPanel
        compact cams={nav.cams} alertCount={nav.alertCount} recentAlerts={nav.recentAlerts}
        latestRec={nav.latestRec} tq={nav.tq} onNavigate={onNavigate}
      />
    );
  }
  if (id === "directory") {
    return (
      <DirectoryPanel
        compact people={nav.people} vehicles={nav.vehicles} facesToName={nav.facesToName}
        tq={nav.tq} onNavigate={onNavigate}
      />
    );
  }
  if (id === "insights") return <InsightsPanel onNavigate={onNavigate} />;
  return <ManagePanel rules={nav.rules} onNavigate={onNavigate} />;
}

/* ────────────────────────────────────────────────────────────────────────
   Mobile: the same grouped surfaces as an accordion. Each header expands to
   reveal its live panel (reusing the exact panel components in compact mode),
   so the phone nav carries the same at-a-glance state as the desktop mega-menu
   rather than being a plain link list.
   ──────────────────────────────────────────────────────────────────────── */
export function MegaNavMobile({ open, onClose }: { open: boolean; onClose: () => void }) {
  const pathname = usePathname();
  const nav = useNavData();
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => { if (!open) setExpanded(null); }, [open]);

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = prev === id ? null : id;
      if (next) nav.ensureData(next);
      return next;
    });
  };

  if (!open) return null;

  return (
    <nav className="md:hidden border-t border-border bg-background max-h-[78vh] overflow-y-auto scrollbar-thin">
      <div className="px-3 py-3 space-y-1.5">
        <Link
          href="/"
          onClick={onClose}
          className={`block rounded-lg px-3 py-2.5 text-sm ${
            pathname === "/" ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground"
          }`}
        >
          Dashboard
        </Link>

        {MENUS.map((m) => {
          const isOpen = expanded === m.id;
          const routeActive = m.links.some((l) => pathname === l.href);
          const showBadge = m.id === "review" && (nav.alertCount ?? 0) > 0;
          return (
            <div key={m.id} className="rounded-lg border border-border-subtle overflow-hidden">
              <button
                onClick={() => toggle(m.id)}
                aria-expanded={isOpen}
                className={`w-full flex items-center gap-2 px-3 py-2.5 text-sm transition-colors ${
                  isOpen ? "bg-muted" : "hover:bg-muted/60"
                }`}
              >
                <span className={routeActive || isOpen ? "text-foreground" : "text-muted-foreground"}>{m.label}</span>
                {showBadge && (
                  <span className="min-w-[16px] h-4 px-1 flex items-center justify-center rounded-full bg-danger/90 text-white text-[9px] font-bold leading-none">
                    {nav.alertCount! > 99 ? "99+" : nav.alertCount}
                  </span>
                )}
                <svg
                  width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2"
                  className={`ml-auto opacity-50 transition-transform duration-200 ${isOpen ? "rotate-180" : ""}`}
                >
                  <path d="M2.5 4.5 L6 8 L9.5 4.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
              {isOpen && (
                <div className="border-t border-border-subtle bg-card/40 p-3">
                  <PanelFor id={m.id} nav={nav} onNavigate={onClose} />
                </div>
              )}
            </div>
          );
        })}

        <Link
          href="/guardian"
          onClick={onClose}
          className={`block rounded-lg px-3 py-2.5 text-sm ${
            pathname.startsWith("/guardian") ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground"
          }`}
        >
          Guardian
        </Link>
      </div>
    </nav>
  );
}
