"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { translate } from "@/lib/i18n";
import { useToast, useConfirm } from "@/lib/feedback";
import { formatDateTime } from "@/lib/time";

interface Person {
  id: string;
  display_name: string;
  nickname: string | null;
  consent_given?: boolean;
}
interface AdminUser {
  id: string;
  email: string;
  display_name: string | null;
  role: string;
}
interface GuardianLink {
  id: string;
  person_id: string;
  guardian_user_id: string;
  relationship_label: string | null;
  tier: string;
  premium: boolean;
  live_presence: boolean;
  live_video: boolean;
  audio: boolean;
  is_primary_parent: boolean;
  revoked_at: string | null;
  expires_at: string | null;
}

const FLAGS: { key: keyof GuardianLink; label: string }[] = [
  { key: "live_presence", label: "Live presence" },
  { key: "live_video", label: "Live video" },
  { key: "audio", label: "Audio" },
  { key: "premium", label: "Premium" },
];

export default function GuardianAdminPage() {
  const { user, authFetch } = useAuth();
  const t = useCallback((key: string) => translate(user?.locale, key), [user?.locale]);
  const [persons, setPersons] = useState<Person[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [links, setLinks] = useState<GuardianLink[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const [pRes, uRes, lRes] = await Promise.all([
        authFetch("/api/persons"),
        authFetch("/api/users"),
        authFetch("/api/guardian/links"),
      ]);
      if (pRes.ok) setPersons(await pRes.json());
      if (uRes.ok) setUsers(await uRes.json());
      if (lRes.ok) setLinks(await lRes.json());
    } finally {
      setLoading(false);
    }
  }, [authFetch]);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 60000);
    return () => clearInterval(t);
  }, [refresh]);

  if (user && user.role !== "admin") {
    return (
      <div className="p-8 text-muted-foreground">
        {t("guardian_admin.admin_only")}
      </div>
    );
  }
  if (loading) return <div className="p-8 text-muted-foreground">{t("guardian_admin.loading")}</div>;

  const personName = (id: string) => {
    const p = persons.find((x) => x.id === id);
    return p ? p.nickname || p.display_name : id.slice(0, 8);
  };
  const userName = (id: string) => {
    const u = users.find((x) => x.id === id);
    return u ? u.display_name || u.email : id.slice(0, 8);
  };

  return (
    <div className="max-w-4xl mx-auto p-6">
      <Link href="/guardian" className="text-sm text-muted-foreground hover:text-foreground">
        ← {t("guardian.title")}
      </Link>
      <h1 className="text-2xl font-semibold tracking-tight mt-3 mb-1">{t("guardian.manage_access")}</h1>
      <p className="text-sm text-muted-foreground mb-6">
        {t("guardian_admin.subtitle")}
      </p>

      <GrantForm persons={persons} users={users} onGranted={refresh} locale={user?.locale} />

      <section className="mt-8">
        <h2 className="text-sm font-medium text-muted-foreground mb-2">{t("guardian_admin.links")}</h2>
        {links.length === 0 ? (
          <div className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
            {t("guardian_admin.no_links")}
          </div>
        ) : (
          <div className="space-y-2">
            {links.map((l) => (
              <LinkRow
                key={l.id}
                link={l}
                personName={personName(l.person_id)}
                guardianName={userName(l.guardian_user_id)}
                onChange={refresh}
                locale={user?.locale}
              />
            ))}
          </div>
        )}
      </section>

      <PickupManager persons={persons} locale={user?.locale} />
      <AccessLog persons={persons} users={users} locale={user?.locale} />
    </div>
  );
}

function GrantForm({
  persons,
  users,
  onGranted,
  locale,
}: {
  persons: Person[];
  users: AdminUser[];
  onGranted: () => void;
  locale?: string;
}) {
  const { authFetch } = useAuth();
  const t = (key: string) => translate(locale, key);
  const [personId, setPersonId] = useState("");
  const [guardianId, setGuardianId] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [tier, setTier] = useState("full");
  const [relationship, setRelationship] = useState("");
  const [primary, setPrimary] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [invite, setInvite] = useState<{ email: string; password: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setErr(null);
    setInvite(null);
    if (!personId || (!guardianId && !inviteEmail.trim())) {
      setErr(t("guardian_admin.pick_person_guardian"));
      return;
    }
    setBusy(true);
    try {
      const payload: Record<string, unknown> = {
        person_id: personId,
        tier,
        relationship_label: relationship || null,
        is_primary_parent: primary,
      };
      if (guardianId) payload.guardian_user_id = guardianId;
      else payload.guardian_email = inviteEmail.trim();
      const res = await authFetch("/api/guardian/links", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const b = await res.json().catch(() => ({}));
        setErr(typeof b.detail === "string" ? b.detail : t("guardian_admin.grant_failed"));
      } else {
        const b = await res.json();
        if (b.guardian_created && b.temp_password) {
          setInvite({ email: b.guardian_email, password: b.temp_password });
        }
        setPersonId("");
        setGuardianId("");
        setInviteEmail("");
        setRelationship("");
        setPrimary(false);
        onGranted();
      }
    } finally {
      setBusy(false);
    }
  };

  const selectedPerson = persons.find((p) => p.id === personId);
  const [consentBusy, setConsentBusy] = useState(false);
  const toggleConsent = async (p: Person) => {
    setConsentBusy(true);
    try {
      await authFetch(`/api/guardian/persons/${p.id}/consent`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ given: !p.consent_given }),
      });
      onGranted();
    } finally {
      setConsentBusy(false);
    }
  };

  return (
    <div className="rounded-lg border border-border bg-card p-5">
      <h2 className="text-sm font-medium mb-3">{t("guardian_admin.grant_guardian")}</h2>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm">
          <span className="text-muted-foreground text-xs">{t("guardian_admin.person")}</span>
          <select
            value={personId}
            onChange={(e) => setPersonId(e.target.value)}
            className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
          >
            <option value="">{t("guardian_admin.select_person")}</option>
            {persons.map((p) => (
              <option key={p.id} value={p.id}>
                {p.nickname || p.display_name}
              </option>
            ))}
          </select>
          {selectedPerson && (
            <div className="mt-1.5 flex items-center gap-2 text-xs">
              <span className={selectedPerson.consent_given ? "text-emerald-400" : "text-amber-400"}>
                {selectedPerson.consent_given ? t("guardian_admin.consent_on_file") : t("guardian_admin.no_consent")}
              </span>
              <button
                type="button"
                disabled={consentBusy}
                onClick={() => toggleConsent(selectedPerson)}
                className="rounded border border-border px-2 py-0.5 hover:bg-muted disabled:opacity-50"
              >
                {selectedPerson.consent_given ? t("guardian_admin.withdraw") : t("guardian_admin.mark_consented")}
              </button>
            </div>
          )}
        </label>
        <label className="text-sm">
          <span className="text-muted-foreground text-xs">{t("guardian_admin.guardian_account")}</span>
          <select
            value={guardianId}
            onChange={(e) => {
              setGuardianId(e.target.value);
              if (e.target.value) setInviteEmail("");
            }}
            className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
          >
            <option value="">{t("guardian_admin.select_user")}</option>
            {users.map((u) => (
              <option key={u.id} value={u.id}>
                {u.display_name || u.email}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm sm:col-span-2">
          <span className="text-muted-foreground text-xs">
            {t("guardian_admin.invite_by_email")}
          </span>
          <input
            type="email"
            value={inviteEmail}
            onChange={(e) => {
              setInviteEmail(e.target.value);
              if (e.target.value) setGuardianId("");
            }}
            placeholder="parent@example.com"
            className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
          />
        </label>
        <label className="text-sm">
          <span className="text-muted-foreground text-xs">{t("guardian_admin.tier")}</span>
          <select
            value={tier}
            onChange={(e) => setTier(e.target.value)}
            className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
          >
            <option value="full">{t("guardian_admin.tier_full")}</option>
            <option value="summary">{t("guardian_admin.tier_summary")}</option>
            <option value="alerts_only">{t("guardian_admin.tier_alerts")}</option>
          </select>
        </label>
        <label className="text-sm">
          <span className="text-muted-foreground text-xs">{t("guardian_admin.relationship")}</span>
          <input
            value={relationship}
            onChange={(e) => setRelationship(e.target.value)}
            placeholder="mother, father, grandparent..."
            className="mt-1 w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
          />
        </label>
      </div>
      <label className="flex items-center gap-2 mt-3 text-sm">
        <input type="checkbox" checked={primary} onChange={(e) => setPrimary(e.target.checked)} />
        <span>{t("guardian_admin.primary_parent")}</span>
      </label>
      {err && <div className="mt-3 text-sm text-red-400">{err}</div>}
      {invite && (
        <div className="mt-3 rounded-md border border-emerald-800 bg-emerald-950/30 p-3 text-sm">
          <div className="font-medium text-emerald-300">{t("guardian_admin.account_created")}</div>
          <div className="mt-1 text-muted-foreground">
            {t("guardian_admin.share_credentials")}
          </div>
          <div className="mt-2 font-mono text-xs">
            <div>email: {invite.email}</div>
            <div>temporary password: {invite.password}</div>
          </div>
        </div>
      )}
      <button
        onClick={submit}
        disabled={busy}
        className="mt-4 px-4 py-1.5 rounded-md bg-emerald-600 hover:bg-emerald-500 text-white text-sm transition-colors disabled:opacity-50"
      >
        {busy ? t("guardian_admin.granting") : t("guardian_admin.grant_access")}
      </button>
    </div>
  );
}

function LinkRow({
  link,
  personName,
  guardianName,
  onChange,
  locale,
}: {
  link: GuardianLink;
  personName: string;
  guardianName: string;
  onChange: () => void;
  locale?: string;
}) {
  const { authFetch } = useAuth();
  const t = (key: string) => translate(locale, key);
  const toast = useToast();
  const confirm = useConfirm();
  const revoked = !!link.revoked_at;

  const patch = async (body: Record<string, unknown>) => {
    await authFetch(`/api/guardian/links/${link.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    onChange();
  };
  const revoke = async () => {
    const ok = await confirm({
      title: t("guardian_admin.revoke_title").replace("{guardian}", guardianName),
      body: t("guardian_admin.revoke_body").replace("{guardian}", guardianName).replace("{person}", personName),
      danger: true,
      confirmLabel: t("guardian_admin.revoke_access"),
    });
    if (!ok) return;
    try {
      const res = await authFetch(`/api/guardian/links/${link.id}`, { method: "DELETE" });
      if (!res.ok && res.status !== 204) throw new Error();
      toast.success(t("guardian_admin.access_revoked"));
      onChange();
    } catch {
      toast.error(t("guardian_admin.revoke_failed"));
    }
  };

  return (
    <div className={`rounded-lg border border-border bg-card p-4 ${revoked ? "opacity-50" : ""}`}>
      <div className="flex items-center justify-between">
        <div>
          <span className="font-medium">{guardianName}</span>
          <span className="text-muted-foreground"> → {personName}</span>
          <span className="ml-2 text-xs rounded bg-muted px-1.5 py-0.5">{link.tier}</span>
          {link.is_primary_parent && (
            <span className="ml-1 text-xs rounded bg-emerald-950/50 text-emerald-300 px-1.5 py-0.5">
              primary
            </span>
          )}
          {revoked && <span className="ml-2 text-xs text-red-400">revoked</span>}
        </div>
        {!revoked && (
          <button
            onClick={revoke}
            className="text-xs text-red-400 hover:text-red-300 border border-red-900/50 rounded px-2 py-1"
          >
            Revoke
          </button>
        )}
      </div>
      {!revoked && (
        <div className="mt-3 flex flex-wrap gap-2">
          {FLAGS.map((f) => {
            const on = !!link[f.key];
            return (
              <button
                key={f.key as string}
                onClick={() => patch({ [f.key]: !on })}
                className={`text-xs rounded-full px-2.5 py-1 border transition-colors ${
                  on
                    ? "bg-emerald-950/50 text-emerald-300 border-emerald-800"
                    : "border-border text-muted-foreground hover:text-foreground"
                }`}
              >
              {t(`guardian_admin.flag_${String(f.key)}`)} {on ? t("guardian_admin.on") : t("guardian_admin.off")}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

interface Pickup {
  id: string;
  name: string;
  kind: string;
  vehicle_plate: string | null;
  active: boolean;
}

function PickupManager({ persons, locale }: { persons: Person[]; locale?: string }) {
  const { authFetch } = useAuth();
  const t = (key: string) => translate(locale, key);
  const [personId, setPersonId] = useState("");
  const [pickups, setPickups] = useState<Pickup[]>([]);
  const [name, setName] = useState("");
  const [kind, setKind] = useState("person");
  const [plate, setPlate] = useState("");

  const load = useCallback(
    async (pid: string) => {
      if (!pid) {
        setPickups([]);
        return;
      }
      const res = await authFetch(`/api/guardian/persons/${pid}/pickups`);
      if (res.ok) setPickups(await res.json());
    },
    [authFetch]
  );

  useEffect(() => {
    // load() only setStates after an await (or to clear on empty selection).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load(personId);
    const t = setInterval(() => load(personId), 60000);
    return () => clearInterval(t);
  }, [personId, load]);

  const add = async () => {
    if (!personId || !name) return;
    const res = await authFetch(`/api/guardian/persons/${personId}/pickups`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, kind, vehicle_plate: plate || null }),
    });
    if (res.ok) {
      setName("");
      setPlate("");
      load(personId);
    }
  };
  const remove = async (id: string) => {
    await authFetch(`/api/guardian/pickups/${id}`, { method: "DELETE" });
    load(personId);
  };

  return (
    <section className="mt-8">
      <h2 className="text-sm font-medium text-muted-foreground mb-2">{t("guardian_admin.approved_pickups")}</h2>
      <div className="rounded-lg border border-border bg-card p-5">
        <select
          value={personId}
          onChange={(e) => setPersonId(e.target.value)}
          className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
        >
          <option value="">{t("guardian_admin.select_pickup_person")}</option>
          {persons.map((p) => (
            <option key={p.id} value={p.id}>
              {p.nickname || p.display_name}
            </option>
          ))}
        </select>

        {personId && (
          <>
            <div className="mt-3 space-y-1.5">
              {pickups.length === 0 && (
                <div className="text-sm text-muted-foreground">{t("guardian_admin.no_pickups")}</div>
              )}
              {pickups.map((pk) => (
                <div
                  key={pk.id}
                  className="flex items-center justify-between text-sm border border-border rounded px-3 py-1.5"
                >
                  <span>
                    {pk.name}
                    <span className="text-muted-foreground text-xs ml-2">
                      {pk.kind}
                      {pk.vehicle_plate ? ` · ${pk.vehicle_plate}` : ""}
                    </span>
                  </span>
                  <button
                    onClick={() => remove(pk.id)}
                    className="text-xs text-red-400 hover:text-red-300"
                  >
                    {t("guardian_admin.remove")}
                  </button>
                </div>
              ))}
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={t("guardian_admin.name")}
                className="flex-1 min-w-[120px] rounded-md border border-border bg-background px-2 py-1.5 text-sm"
              />
              <select
                value={kind}
                onChange={(e) => setKind(e.target.value)}
                className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
              >
                <option value="person">{t("guardian_admin.person_kind")}</option>
                <option value="vehicle">{t("guardian_admin.vehicle_kind")}</option>
              </select>
              {kind === "vehicle" && (
                <input
                  value={plate}
                  onChange={(e) => setPlate(e.target.value)}
                  placeholder={t("guardian_admin.plate")}
                  className="w-28 rounded-md border border-border bg-background px-2 py-1.5 text-sm"
                />
              )}
              <button
                onClick={add}
                className="px-3 py-1.5 rounded-md border border-border text-sm hover:bg-muted"
              >
                {t("guardian_admin.add")}
              </button>
            </div>
          </>
        )}
      </div>
    </section>
  );
}

interface LogEntry {
  id: string;
  guardian_user_id: string;
  person_id: string;
  action: string;
  at: string;
}

function AccessLog({ persons, users, locale }: { persons: Person[]; users: AdminUser[]; locale?: string }) {
  const { authFetch } = useAuth();
  const t = (key: string) => translate(locale, key);
  const [entries, setEntries] = useState<LogEntry[]>([]);

  const load = useCallback(async () => {
    try {
      const r = await authFetch("/api/guardian/access-log?limit=50");
      setEntries(r.ok ? await r.json() : []);
    } catch {
      setEntries([]);
    }
  }, [authFetch]);

  useEffect(() => {
    // load() only setStates after the awaited fetch resolves.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, [load]);

  const pName = (id: string) => persons.find((p) => p.id === id)?.display_name || id.slice(0, 8);
  const uName = (id: string) =>
    users.find((u) => u.id === id)?.display_name || users.find((u) => u.id === id)?.email || id.slice(0, 8);

  return (
    <section className="mt-8 mb-12">
      <h2 className="text-sm font-medium text-muted-foreground mb-2">{t("guardian_admin.access_log")}</h2>
      <div className="rounded-lg border border-border bg-card divide-y divide-border max-h-80 overflow-auto">
        {entries.length === 0 ? (
          <div className="p-4 text-sm text-muted-foreground">{t("guardian_admin.no_access")}</div>
        ) : (
          entries.map((e) => (
            <div key={e.id} className="flex items-center justify-between px-4 py-2 text-xs">
              <span>
                <span className="text-foreground">{uName(e.guardian_user_id)}</span>{" "}
                <span className="text-muted-foreground">{e.action}</span>{" "}
                <span className="text-foreground">{pName(e.person_id)}</span>
              </span>
              <span className="text-muted-foreground">{formatDateTime(e.at)}</span>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
