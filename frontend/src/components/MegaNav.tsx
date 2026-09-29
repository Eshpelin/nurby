"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";
import { translate } from "@/lib/i18n";
import { getDisplayLocale } from "@/lib/time";

/* ────────────────────────────────────────────────────────────────────────
   Mega navigation. Ten flat links collapse into four grouped triggers, each
   opening a single shared panel that morphs (position + width) between them
   while its content cross-fades. Every panel surfaces live state for its
   domain (unreviewed alerts, who was just seen, active rules) so the nav is a
   glance-able console, not just a link list.
   ──────────────────────────────────────────────────────────────────────── */

type LinkDef = { label: string; href: string; hint: string };
type MenuDef = { id: string; label: string; links: LinkDef[] };

const NAV_KEYS: Record<string, string> = {
  Home: "nav.home", Cameras: "nav.cameras", Settings: "nav.settings",
  Activity: "nav.activity", Ask: "nav.ask", People: "nav.people",
  Everything: "nav.everything", Alerts: "nav.alerts", Incidents: "nav.incidents",
  Journeys: "nav.journeys", Conversations: "nav.conversations", Recordings: "nav.recordings",
  Memory: "nav.memory", "Scheduled questions": "nav.scheduled_questions", Vehicles: "nav.vehicles",
};

function navLabel(value: string, locale: string | undefined): string {
  const key = NAV_KEYS[value];
  return key ? translate(locale, key) : value;
}

const HINT_KEYS: Record<string, string> = {
  "Is everything all right": "nav.hint.home",
  "Show me": "nav.hint.cameras",
  "Configure Nurby": "nav.hint.settings",
  "What happened, newest first": "nav.hint.everything",
  "What your rules raised": "nav.hint.alerts",
  "Repeat sightings, grouped": "nav.hint.incidents",
  "One subject across cameras": "nav.hint.journeys",
  "Speech near a camera": "nav.hint.conversations",
  "Browse & filter footage": "nav.hint.recordings",
  "What each camera concluded": "nav.hint.camera_recaps",
  "Find anything in your footage": "nav.hint.search",
  "Question your footage": "nav.hint.ask_nurby",
  "Household notes & what Nurby learned": "nav.hint.memory",
  "Questions answered on a clock": "nav.hint.scheduled",
  "Faces & identities": "nav.hint.people",
  "Plates & re-ID": "nav.hint.vehicles",
};

function navHint(value: string, locale: string | undefined): string {
  const key = HINT_KEYS[value];
  return key ? translate(locale, key) : value;
}

const MENUS: MenuDef[] = [
  // The five places (docs/ia-rollout.md). Each is the question it
  // answers. Home and Cameras are plain links; the other three keep the
  // glance-able panel because that is where the live state is useful.
  {
    id: "activity",
    label: "Activity",
    links: [
      { label: "Everything", href: "/activity", hint: "What happened, newest first" },
      { label: "Alerts", href: "/events", hint: "What your rules raised" },
      { label: "Incidents", href: "/activity?kind=incidents", hint: "Repeat sightings, grouped" },
      { label: "Journeys", href: "/activity?kind=journeys", hint: "One subject across cameras" },
      { label: "Conversations", href: "/activity?kind=conversations", hint: "Speech near a camera" },
      { label: "Recordings", href: "/recordings", hint: "Browse & filter footage" },
      { label: "Camera recaps", href: "/activity?kind=recaps", hint: "What each camera concluded" },
      { label: "Search", href: "/search", hint: "Find anything in your footage" },
    ],
  },
  {
    id: "ask",
    label: "Ask",
    links: [
      { label: "Ask Nurby", href: "/ask", hint: "Question your footage" },
      { label: "Memory", href: "/memory", hint: "Household notes & what Nurby learned" },
      { label: "Scheduled questions", href: "/reports", hint: "Questions answered on a clock" },
    ],
  },
  {
    id: "people",
    label: "People",
    links: [
      { label: "People", href: "/people", hint: "Faces & identities" },
      { label: "Vehicles", href: "/vehicles", hint: "Plates & re-ID" },
    ],
  },
];

/** Plain links that need no panel. */
const PLAIN: LinkDef[] = [
  { label: "Home", href: "/", hint: "Is everything all right" },
  { label: "Cameras", href: "/cameras", hint: "Show me" },
  { label: "Settings", href: "/settings", hint: "Configure Nurby" },
];

// Panel width per menu (px). The shared card transitions between these, which
// is what gives the morph its feel; keep them distinct but not jarring.
const PANEL_WIDTH: Record<string, number> = {
  activity: 620,
  ask: 480,
  people: 600,
};

function timeAgo(iso?: string | null, locale?: string): string {
  if (!iso) return "";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return translate(locale, "nav.time_just_now");
  if (s < 3600) return translate(locale, "nav.time_minutes", { count: Math.floor(s / 60) });
  if (s < 86400) return translate(locale, "nav.time_hours", { count: Math.floor(s / 3600) });
  return translate(locale, "nav.time_days", { count: Math.floor(s / 86400) });
}

function initials(name?: string | null): string {
  if (!name) return "?";
  return name.split(" ").map((w) => w[0]).join("").toUpperCase().slice(0, 2);
}

// "Living Room · 2m ago", or just one part, or "Not seen yet" — never a
// dangling separator.
function seenLabel(camera?: string | null, iso?: string | null, locale?: string): string {
  const parts = [camera, timeAgo(iso, locale)].filter(Boolean);
  return parts.length ? parts.join(" · ") : translate(locale, "nav.no_one_yet");
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
      if (id === "activity") {
        const [a, rec] = await Promise.all([
          authFetch("/api/events/history?acked=false&limit=3"),
          authFetch("/api/recordings?limit=1"),
        ]);
        if (a.ok) setRecentAlerts(await a.json());
        if (rec.ok) { const list = await rec.json(); setLatestRec(list[0] ?? null); }
      } else if (id === "people") {
        const [p, v, s] = await Promise.all([
          authFetch("/api/persons/activity/summary"),
          authFetch("/api/vehicles/activity/summary"),
          authFetch("/api/persons/suggestions?min_sightings=2"),
        ]);
        if (p.ok) setPeople((await p.json()).slice(0, 4));
        if (v.ok) setVehicles((await v.json()).slice(0, 3));
        if (s.ok) setFacesToName((await s.json()).length);
      }
    } catch {
      fetched.current[id] = false; // allow a retry on the next open
    }
  }, [authFetch]);

  return { cams, alertCount, recentAlerts, latestRec, people, vehicles, facesToName, rules, ensureData, tq };
}

export function MegaNav() {
  const pathname = usePathname();
  const [locale, setLocale] = useState<string | undefined>(() => getDisplayLocale());
  const {
    cams, alertCount, recentAlerts, latestRec, people, vehicles, facesToName, rules, ensureData, tq,
  } = useNavData();

  useEffect(() => {
    const onLocaleChange = (event: Event) => setLocale((event as CustomEvent<string>).detail || "en");
    window.addEventListener("nurby-locale-change", onLocaleChange);
    return () => window.removeEventListener("nurby-locale-change", onLocaleChange);
  }, []);

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
        {PLAIN.map((l) => (
          <Link
            key={l.href}
            href={l.href}
            title={navHint(l.hint, locale)}
            className={`px-3 py-1.5 rounded-md text-sm transition-colors whitespace-nowrap ${
              (l.href === "/" ? pathname === "/" : pathname.startsWith(l.href))
                ? "bg-muted text-foreground"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {navLabel(l.label, locale)}
          </Link>
        ))}

        {MENUS.map((m) => {
          const on = active === m.id;
          const routeActive = isMenuActive(m);
          const showAlertBadge = m.id === "activity" && (alertCount ?? 0) > 0;
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
              {navLabel(m.label, locale)}
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
              {active === "activity" && (
                <ReviewPanel
                  cams={cams} alertCount={alertCount} recentAlerts={recentAlerts}
                  latestRec={latestRec} tq={tq} locale={locale} onNavigate={() => setActive(null)}
                />
              )}
              {active === "people" && (
                <DirectoryPanel
                  people={people} vehicles={vehicles} facesToName={facesToName}
                  tq={tq} locale={locale} onNavigate={() => setActive(null)}
                />
              )}
              {active === "ask" && <InsightsPanel locale={locale} onNavigate={() => setActive(null)} />}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── panel building blocks ─────────────────────────────────────────────── */

function PanelLinks({ links, onNavigate, locale }: { links: LinkDef[]; onNavigate: () => void; locale?: string }) {
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
            <span className="block text-sm text-foreground">{navLabel(l.label, getDisplayLocale())}</span>
            <span className="block text-[11px] text-muted-foreground">{navHint(l.hint, locale)}</span>
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
  cams, alertCount, recentAlerts, latestRec, tq, onNavigate, compact, locale,
}: {
  cams: Record<string, string>; alertCount: number | null; recentAlerts: EventRow[];
  latestRec: { id: string; started_at: string; camera_id: string } | null;
  tq: string; onNavigate: () => void; compact?: boolean; locale?: string;
}) {
  return (
    <div className={`grid gap-3 ${compact ? "grid-cols-1" : "grid-cols-[1.35fr_1fr]"}`}>
      <div>
        <SectionLabel>{translate(locale, "nav.needs_review")}</SectionLabel>
        <Link
          href="/events"
          onClick={onNavigate}
          className="mega-item block rounded-lg border border-border bg-card p-3 hover:border-accent/50 transition-colors"
          style={{ animationDelay: "40ms" }}
        >
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-semibold tabular-nums">{alertCount ?? "—"}</span>
            <span className="text-xs text-muted-foreground">{translate(locale, alertCount === 1 ? "nav.unreviewed_one" : "nav.unreviewed_many")}</span>
            {(alertCount ?? 0) > 0 && <span className="ml-auto w-2 h-2 rounded-full bg-danger pulse-dot" />}
          </div>
          <ul className="mt-2 space-y-1">
            {recentAlerts.length === 0 && <li className="text-[11px] text-muted-foreground">{translate(locale, "nav.all_caught_up")}</li>}
            {recentAlerts.map((e, i) => (
              <li key={e.id} className="mega-item flex items-center gap-2 text-[11px]" style={{ animationDelay: `${120 + i * 50}ms` }}>
                <span className="w-1 h-1 rounded-full bg-accent shrink-0" />
                <span className="text-foreground truncate">{objectLabel(e)}</span>
                <span className="text-muted-foreground truncate">{cams[e.payload?.camera_id ?? ""] || translate(locale, "nav.camera")}</span>
                <span className="ml-auto font-mono text-muted-foreground/70 shrink-0">{timeAgo(e.fired_at, locale)}</span>
              </li>
            ))}
          </ul>
        </Link>
      </div>

      <div>
        <SectionLabel>{translate(locale, "nav.latest_footage")}</SectionLabel>
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
              {latestRec ? (cams[latestRec.camera_id] || translate(locale, "nav.camera")) : translate(locale, "nav.no_recordings")}
            </div>
            {latestRec && <div className="text-[10px] font-mono text-muted-foreground">{timeAgo(latestRec.started_at, locale)}</div>}
          </div>
        </Link>
      </div>

      <div className="col-span-2">
        <PanelLinks links={MENUS[0].links} onNavigate={onNavigate} locale={locale} />
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
  people, vehicles, facesToName, tq, onNavigate, compact, locale,
}: {
  people: PersonSummary[]; vehicles: VehicleSummary[]; facesToName: number | null;
  tq: string; onNavigate: () => void; compact?: boolean; locale?: string;
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
          {facesToName} {translate(locale, facesToName === 1 ? "nav.new_face_one" : "nav.new_face_many")}
          <span className="ml-auto">→</span>
        </Link>
      )}
      <div className={`grid gap-3 ${compact ? "grid-cols-1" : "grid-cols-2"}`}>
        <div>
          <SectionLabel>{translate(locale, "nav.recently_seen")}</SectionLabel>
          <div className="space-y-1">
            {people.length === 0 && <div className="text-[11px] text-muted-foreground px-1">{translate(locale, "nav.no_one_yet")}</div>}
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
                    {seenLabel(p.last_seen_camera, p.last_seen_at, locale)}
                  </span>
                </span>
              </Link>
            ))}
          </div>
        </div>
        <div>
          <SectionLabel>{translate(locale, "nav.recent_vehicles")}</SectionLabel>
          <div className="space-y-1">
            {vehicles.length === 0 && <div className="text-[11px] text-muted-foreground px-1">{translate(locale, "nav.none_yet")}</div>}
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
                    {seenLabel(v.last_seen_camera, v.last_seen_at, locale)}
                  </span>
                </span>
              </Link>
            ))}
          </div>
        </div>
      </div>
      <PanelLinks links={MENUS[2].links} onNavigate={onNavigate} locale={locale} />
    </div>
  );
}

const QUICK_ASKS = ["nav.quick_ask_door", "nav.quick_ask_vehicle", "nav.quick_ask_night"];

function InsightsPanel({ onNavigate, locale }: { onNavigate: () => void; locale?: string }) {
  return (
    <div>
      <SectionLabel>{translate(locale, "nav.ask_nurby")}</SectionLabel>
      <Link
        href="/ask"
        onClick={onNavigate}
        className="mega-item flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2.5 text-sm text-muted-foreground hover:border-accent/50 transition-colors"
        style={{ animationDelay: "40ms" }}
      >
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-accent">
          <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        {translate(locale, "nav.ask_placeholder")}
      </Link>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {QUICK_ASKS.map((q, i) => (
          <Link
            key={q}
            href={`/ask?q=${encodeURIComponent(translate(locale, q))}`}
            onClick={onNavigate}
            className="mega-item rounded-full border border-border-subtle px-2.5 py-1 text-[11px] text-muted-foreground hover:text-foreground hover:border-accent/40 transition-colors"
            style={{ animationDelay: `${90 + i * 45}ms` }}
          >
            {translate(locale, q)}
          </Link>
        ))}
      </div>
      <PanelLinks links={MENUS[1].links} onNavigate={onNavigate} locale={locale} />
    </div>
  );
}

function PanelFor({ id, nav, locale, onNavigate }: { id: string; nav: NavData; locale?: string; onNavigate: () => void }) {
  if (id === "activity") {
    return (
      <ReviewPanel
        compact cams={nav.cams} alertCount={nav.alertCount} recentAlerts={nav.recentAlerts}
        latestRec={nav.latestRec} tq={nav.tq} locale={locale} onNavigate={onNavigate}
      />
    );
  }
  if (id === "people") {
    return (
      <DirectoryPanel
        compact people={nav.people} vehicles={nav.vehicles} facesToName={nav.facesToName}
        tq={nav.tq} locale={locale} onNavigate={onNavigate}
      />
    );
  }
  if (id === "ask") return <InsightsPanel locale={locale} onNavigate={onNavigate} />;
  return null;
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
  const [locale, setLocale] = useState<string | undefined>(() => getDisplayLocale());
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    const onLocaleChange = (event: Event) => setLocale((event as CustomEvent<string>).detail || "en");
    window.addEventListener("nurby-locale-change", onLocaleChange);
    return () => window.removeEventListener("nurby-locale-change", onLocaleChange);
  }, []);

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
          {navLabel("Home", locale)}
        </Link>

        {MENUS.map((m) => {
          const isOpen = expanded === m.id;
          const routeActive = m.links.some((l) => pathname === l.href);
          const showBadge = m.id === "activity" && (nav.alertCount ?? 0) > 0;
          return (
            <div key={m.id} className="rounded-lg border border-border-subtle overflow-hidden">
              <button
                onClick={() => toggle(m.id)}
                aria-expanded={isOpen}
                className={`w-full flex items-center gap-2 px-3 py-2.5 text-sm transition-colors ${
                  isOpen ? "bg-muted" : "hover:bg-muted/60"
                }`}
              >
                <span className={routeActive || isOpen ? "text-foreground" : "text-muted-foreground"}>{navLabel(m.label, locale)}</span>
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
                  <PanelFor id={m.id} nav={nav} locale={locale} onNavigate={onClose} />
                </div>
              )}
            </div>
          );
        })}

        {PLAIN.filter((l) => l.href !== "/").map((l) => (
          <Link
            key={l.href}
            href={l.href}
            onClick={onClose}
            title={navHint(l.hint, locale)}
            className={`block rounded-lg px-3 py-2.5 text-sm ${
              pathname.startsWith(l.href) ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {navLabel(l.label, locale)}
          </Link>
        ))}

        
      </div>
    </nav>
  );
}
