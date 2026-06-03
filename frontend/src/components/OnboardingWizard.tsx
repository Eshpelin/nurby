"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";
import CameraBrandHelp from "@/components/CameraBrandHelp";
import { OllamaDeployPanel } from "@/components/OllamaDeployPanel";
import { AddCameraModal } from "@/components/AddCameraModal";
import { ONBOARDING_PRESETS } from "@/lib/provider-presets";

interface Provider {
  id: string;
  name: string;
  kind: string;
  base_url: string;
  default_model: string | null;
  active: boolean;
}

interface Props {
  onClose: () => void;
  onComplete: () => void;
}

type Step = "choose" | "magic" | "camera" | "provider" | "done";

// Curated subset of the shared provider catalog (see @/lib/provider-presets).
const PROVIDER_PRESETS = ONBOARDING_PRESETS;


/**
 * Three-step first-run modal, ordered for the fastest path to a live feed:
 *   1. camera  (demo camera is the default. one click and you're watching)
 *   2. provider (optional VLM. detection, faces and rules work without it,
 *      so this step defaults to a pure Next)
 *   3. done
 *
 * Every step is skippable. Completing the wizard sets a localStorage flag
 * so it does not pop up again. The dashboard decides when to mount this
 * (see /app/page.tsx).
 */
export function OnboardingWizard({ onClose, onComplete }: Props) {
  const { authFetch } = useAuth();
  const [step, setStep] = useState<Step>("choose");
  const [providers, setProviders] = useState<Provider[]>([]);

  // Persist dismissal both locally (fast path) and server-side (so it
  // survives a browser/device change; an admin can re-trigger the wizard
  // by flipping onboarding_dismissed back to false in Settings).
  const markDismissed = useCallback(() => {
    try {
      localStorage.setItem("nurby-onboarding-dismissed", "1");
    } catch {
      /* ignore */
    }
    authFetch("/api/system/settings", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ onboarding_dismissed: true }),
    }).catch(() => {
      /* best-effort; localStorage still gates this browser */
    });
  }, [authFetch]);

  // Provider step state.
  const [presetIdx, setPresetIdx] = useState<number>(0);
  const [providerName, setProviderName] = useState<string>(PROVIDER_PRESETS[0].name);
  const [providerApiKey, setProviderApiKey] = useState<string>("");
  const [providerModel, setProviderModel] = useState<string>(PROVIDER_PRESETS[0].default_model);
  const [providerBaseUrl, setProviderBaseUrl] = useState<string>(PROVIDER_PRESETS[0].base_url);
  const [providerSubmitting, setProviderSubmitting] = useState(false);
  const [providerError, setProviderError] = useState<string | null>(null);
  // Connection-test state. After we create the provider row we hit the
  // backend test endpoint so a wrong key / unreachable endpoint fails
  // fast in the wizard instead of silently later. ForceAdvance lets the
  // user proceed past a failed test on a second click.
  const [providerTestMsg, setProviderTestMsg] = useState<string | null>(null);
  const [providerForceAdvance, setProviderForceAdvance] = useState(false);
  const [createdProviderId, setCreatedProviderId] = useState<string | null>(null);
  // The step leads with local Ollama auto-deploy (no key, fully private).
  // cloudMode reveals the secondary path for a hosted provider. The pure
  // skip is always available in the footer since detection, faces and
  // rules work without any VLM.
  const [cloudMode, setCloudMode] = useState(false);


  const preset = PROVIDER_PRESETS[presetIdx];

  // Auto-pick provider name + default model + base url from preset.
  useEffect(() => {
    setProviderName(PROVIDER_PRESETS[presetIdx].name);
    setProviderModel(PROVIDER_PRESETS[presetIdx].default_model);
    setProviderBaseUrl(PROVIDER_PRESETS[presetIdx].base_url);
  }, [presetIdx]);

  // The Ollama deploy endpoint auto-creates the provider. Refresh the
  // provider list and finish, since this is the last meaningful step.
  async function onOllamaProvisioned() {
    try {
      const r = await authFetch("/api/providers");
      if (r.ok) setProviders(await r.json());
    } catch {
      /* non-fatal. The provider was created server-side regardless */
    }
    setStep("done");
  }

  // Hydrate existing providers so we can skip step 2 if one already
  // exists.
  useEffect(() => {
    (async () => {
      try {
        const r = await authFetch("/api/providers");
        if (r.ok) {
          const list: Provider[] = await r.json();
          setProviders(list);
        }
      } catch {
        /* ignore */
      }
    })();
  }, [authFetch]);

  async function createProvider(): Promise<Provider | null> {
    setProviderError(null);
    setProviderSubmitting(true);
    try {
      const body: Record<string, unknown> = {
        name: providerName.trim() || preset.name,
        kind: preset.kind,
        base_url: providerBaseUrl.trim() || preset.base_url,
        default_model: providerModel.trim() || preset.default_model,
        active: true,
      };
      if (preset.keyRequired) {
        if (!providerApiKey.trim()) {
          setProviderError("API key is required for this provider");
          return null;
        }
        body.api_key = providerApiKey.trim();
      }
      const res = await authFetch("/api/providers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const j = await res.json().catch(() => ({}));
        setProviderError(j.detail || `Failed (${res.status})`);
        return null;
      }
      const created: Provider = await res.json();
      setProviders((prev) => [...prev, created]);
      setCreatedProviderId(created.id);
      return created;
    } finally {
      setProviderSubmitting(false);
    }
  }

  /** Hit /providers/{id}/test. Returns true on a confirmed connection. */
  async function testProvider(providerId: string): Promise<boolean> {
    setProviderTestMsg("Testing connection...");
    try {
      const res = await authFetch(`/api/providers/${providerId}/test`, {
        method: "POST",
      });
      const j = await res.json().catch(() => ({}));
      if (res.ok && j.ok) {
        const lat = j.latency_ms != null ? ` (${j.latency_ms}ms)` : "";
        setProviderTestMsg(`Connected${lat}. ${j.message || ""}`.trim());
        return true;
      }
      setProviderTestMsg(
        `Connection test failed: ${j.message || j.detail || `status ${res.status}`}. ` +
          "Check the key / URL, or click again to continue anyway.",
      );
      return false;
    } catch {
      setProviderTestMsg(
        "Could not reach the provider to test it. Click again to continue anyway.",
      );
      return false;
    }
  }

  function dismiss() {
    markDismissed();
    onClose();
  }

  // Escape closes the wizard, except while magic is provisioning (work is
  // in flight and a half-finished close would be confusing).
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && step !== "magic") dismiss();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
      <div className="rounded-xl border border-border bg-card w-full max-w-2xl shadow-2xl flex flex-col max-h-[90vh]">
        <div className="px-5 py-3 border-b border-border flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-accent" />
            <h2 className="text-sm font-semibold uppercase tracking-wider">
              Set up Nurby
            </h2>
            {(step === "camera" || step === "provider" || step === "done") && (
              <span className="text-xs text-muted-foreground">
                Step {stepNumber(step)} of 3
              </span>
            )}
          </div>
          {step !== "magic" && (
            <button
              onClick={dismiss}
              className="text-xs text-muted-foreground hover:text-foreground"
            >
              Skip for now
            </button>
          )}
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-5">
          {step === "choose" && (
            <ChooseStep
              onMagic={() => setStep("magic")}
              onManual={() => setStep("camera")}
            />
          )}
          {step === "magic" && (
            <MagicStep
              onDone={() => {
                markDismissed();
                onComplete();
              }}
              onFallback={() => setStep("camera")}
            />
          )}
          {step === "camera" && (
            <CameraStep onAdded={() => setStep("provider")} />
          )}
          {step === "provider" && (
            <ProviderStep
              presets={PROVIDER_PRESETS}
              presetIdx={presetIdx}
              setPresetIdx={setPresetIdx}
              providerName={providerName}
              setProviderName={setProviderName}
              providerApiKey={providerApiKey}
              setProviderApiKey={setProviderApiKey}
              providerModel={providerModel}
              setProviderModel={setProviderModel}
              providerBaseUrl={providerBaseUrl}
              setProviderBaseUrl={setProviderBaseUrl}
              onProvisioned={onOllamaProvisioned}
              error={providerError}
              testMsg={providerTestMsg}
              cloudMode={cloudMode}
              setCloudMode={(b) => {
                setCloudMode(b);
                // Default the cloud picker to OpenAI, not Ollama, since the
                // panel above already owns the local path.
                if (b && presetIdx === 0) setPresetIdx(1);
              }}
            />
          )}
          {step === "done" && (
            <DoneStep onClose={() => {
              markDismissed();
              onComplete();
            }} />
          )}
        </div>

        {step !== "choose" && step !== "magic" && (
        <div className="px-5 py-3 border-t border-border flex items-center justify-between">
          <button
            onClick={() => {
              if (step === "provider") setStep("camera");
              else if (step === "camera") setStep("choose");
            }}
            className={`px-3 py-1.5 text-xs rounded-md border border-border hover:bg-muted ${
              step === "done" ? "invisible" : ""
            }`}
          >
            Back
          </button>
          {step === "camera" && (
            <button
              onClick={() => setStep("provider")}
              className="px-4 py-1.5 text-xs rounded-md border border-border hover:bg-muted text-muted-foreground"
            >
              Skip for now
            </button>
          )}
          {step === "provider" && !cloudMode && (
            <button
              onClick={() => setStep("done")}
              className="px-4 py-1.5 text-xs rounded-md border border-border hover:bg-muted text-muted-foreground"
            >
              Skip for now
            </button>
          )}
          {step === "provider" && cloudMode && (
            <button
              onClick={async () => {
                // Second click after a failed test = proceed anyway.
                if (providerForceAdvance) {
                  setStep("done");
                  return;
                }
                // Create the row if not already created, then test it.
                let pid = createdProviderId;
                if (!pid) {
                  const created = await createProvider();
                  if (!created) return;
                  pid = created.id;
                }
                const ok = await testProvider(pid);
                if (ok) {
                  setStep("done");
                } else {
                  // Allow the next click to advance past the failure.
                  setProviderForceAdvance(true);
                }
              }}
              disabled={providerSubmitting}
              className="px-4 py-1.5 text-xs rounded-md bg-accent text-accent-foreground font-medium hover:opacity-90 disabled:opacity-50"
            >
              {providerSubmitting
                ? "Adding."
                : providerForceAdvance
                ? "Continue anyway"
                : "Add & test"}
            </button>
          )}
          {step === "done" && (
            <button
              onClick={() => {
                markDismissed();
                onComplete();
              }}
              className="px-4 py-1.5 text-xs rounded-md bg-accent text-accent-foreground font-medium hover:opacity-90"
            >
              Open dashboard
            </button>
          )}
        </div>
        )}
      </div>
    </div>
  );
}

function stepNumber(s: Step): number {
  if (s === "camera") return 1;
  if (s === "provider") return 2;
  return 3;
}

// First fork. one-click "magic" that provisions everything locally, or the
// hands-on path for people who want to wire their own camera and model.
function ChooseStep({
  onMagic,
  onManual,
}: {
  onMagic: () => void;
  onManual: () => void;
}) {
  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-xl font-semibold">Welcome to Nurby</h3>
        <p className="text-sm text-muted-foreground leading-relaxed mt-1">
          Pick how you want to start. You can change anything later.
        </p>
      </div>

      <div className="grid sm:grid-cols-2 gap-3">
        {/* Magic. the hero path. */}
        <button
          type="button"
          onClick={onMagic}
          className="group text-left rounded-xl border border-accent/40 bg-gradient-to-br from-accent/10 to-transparent p-4 hover:border-accent transition-colors"
        >
          <div className="flex items-center gap-2 mb-2">
            <span className="text-lg leading-none">✨</span>
            <span className="text-sm font-semibold">Show me some magic</span>
          </div>
          <p className="text-[12px] text-muted-foreground leading-relaxed">
            One click. Nurby adds a live demo camera, sets up a private local
            vision model if you don&apos;t have one, and drops you on the
            dashboard. Nothing leaves your machine.
          </p>
          <span className="inline-block mt-3 text-[11px] font-medium text-accent group-hover:underline">
            Do it all for me →
          </span>
        </button>

        {/* Manual. */}
        <button
          type="button"
          onClick={onManual}
          className="text-left rounded-xl border border-border bg-card/40 p-4 hover:border-muted-foreground transition-colors"
        >
          <div className="flex items-center gap-2 mb-2">
            <span className="text-lg leading-none">🛠️</span>
            <span className="text-sm font-semibold">Set it up myself</span>
          </div>
          <p className="text-[12px] text-muted-foreground leading-relaxed">
            I know what I&apos;m doing. Walk me through adding my own camera and
            choosing a vision model, local or cloud.
          </p>
          <span className="inline-block mt-3 text-[11px] font-medium text-muted-foreground">
            Start the guided setup →
          </span>
        </button>
      </div>
    </div>
  );
}

// The magic. Runs the minimal provisioning sequence end to end with a live
// progress bar, then lands on the dashboard. Every step is best-effort. a
// missing local AI never blocks the camera, since detection, faces and
// rules work without a VLM.
function MagicStep({
  onDone,
  onFallback,
}: {
  onDone: () => void;
  onFallback: () => void;
}) {
  const { authFetch } = useAuth();
  const [pct, setPct] = useState(6);
  const [label, setLabel] = useState("Setting up your space");
  const [tasks, setTasks] = useState<{ camera: TaskState; vlm: TaskState }>({
    camera: "pending",
    vlm: "pending",
  });
  const [error, setError] = useState<string | null>(null);
  // Run the provisioning sequence exactly once per mount lifetime. Guards
  // against a strict-mode double-invoke or any remount firing two demo
  // POSTs and two deploys.
  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    let cancelled = false;
    let creep: ReturnType<typeof setInterval> | null = null;
    const set = (p: number, l?: string) => {
      if (cancelled) return;
      setPct((prev) => Math.max(prev, p));
      if (l) setLabel(l);
    };

    (async () => {
      // 1. Demo camera.
      set(12, "Adding a live demo camera");
      setTasks((t) => ({ ...t, camera: "running" }));
      try {
        const r = await authFetch("/api/cameras/demo", { method: "POST" });
        if (!r.ok && r.status !== 409) throw new Error(String(r.status));
        if (!cancelled) setTasks((t) => ({ ...t, camera: "done" }));
      } catch {
        // The camera is the one thing we truly need. If it fails, hand off
        // to the manual flow rather than landing on an empty dashboard.
        if (!cancelled) {
          setError("Could not add the demo camera. Let's set it up by hand.");
          setTimeout(() => !cancelled && onFallback(), 1800);
        }
        return;
      }

      // 2. Local vision model (best-effort).
      set(32, "Looking for local AI");
      setTasks((t) => ({ ...t, vlm: "running" }));
      let reachable = false;
      let model = "gemma3:4b";
      try {
        const sr = await authFetch("/api/ollama/status");
        if (sr.ok) {
          const s = await sr.json();
          reachable = !!(s.installed || s.running);
          model = s.recommended_model || model;
        }
      } catch {
        /* treat as no local AI */
      }

      if (reachable) {
        set(42, "Deploying a private vision model. This can take a few minutes");
        // Smoothly creep the bar while the (long) pull runs.
        creep = setInterval(() => {
          if (cancelled) return;
          setPct((prev) => (prev < 88 ? prev + 2 : prev));
        }, 1500);
        try {
          const dr = await authFetch("/api/ollama/deploy", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ model }),
          });
          const data = await dr.json().catch(() => ({}));
          if (creep) clearInterval(creep);
          if (dr.ok && data.stage === "done") {
            if (!cancelled) setTasks((t) => ({ ...t, vlm: "done" }));
          } else {
            if (!cancelled) setTasks((t) => ({ ...t, vlm: "skipped" }));
          }
        } catch {
          if (creep) clearInterval(creep);
          if (!cancelled) setTasks((t) => ({ ...t, vlm: "skipped" }));
        }
      } else {
        // No local AI available. Skip honestly. the product still works.
        if (!cancelled) setTasks((t) => ({ ...t, vlm: "skipped" }));
      }

      // 3. Done.
      set(100, "Ready");
      setTimeout(() => {
        if (!cancelled) onDone();
      }, 800);
    })();

    return () => {
      cancelled = true;
      if (creep) clearInterval(creep);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="space-y-5 py-2">
      <div className="text-center space-y-1">
        <div className="text-3xl">✨</div>
        <h3 className="text-lg font-semibold">Working some magic</h3>
        <p className="text-xs text-muted-foreground">
          Sit tight. Setting up everything you need to see Nurby in action.
        </p>
      </div>

      {/* Progress bar */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between text-[11px]">
          <span className="text-muted-foreground">{label}</span>
          <span className="font-mono font-medium">{Math.round(pct)}%</span>
        </div>
        <div className="h-2 rounded-full bg-muted overflow-hidden">
          <div
            className="h-full bg-accent transition-[width] duration-700 ease-out"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      {/* Task checklist */}
      <div className="space-y-2">
        <MagicTaskRow state={tasks.camera} label="Add a live demo camera" />
        <MagicTaskRow
          state={tasks.vlm}
          label="Set up a private local vision model"
          skippedNote="No local AI found. added later from Settings"
        />
      </div>

      {error && (
        <div className="text-[11px] text-amber-400 bg-amber-500/10 border border-amber-500/30 rounded-md px-2.5 py-1.5">
          {error}
        </div>
      )}
    </div>
  );
}

type TaskState = "pending" | "running" | "done" | "skipped";

function MagicTaskRow({
  state,
  label,
  skippedNote,
}: {
  state: TaskState;
  label: string;
  skippedNote?: string;
}) {
  return (
    <div className="flex items-center gap-2.5 text-xs">
      <span className="w-4 h-4 flex items-center justify-center flex-shrink-0">
        {state === "done" && (
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" className="text-emerald-400">
            <polyline points="20 6 9 17 4 12" />
          </svg>
        )}
        {state === "running" && (
          <span className="w-3.5 h-3.5 rounded-full border-2 border-accent border-t-transparent animate-spin" />
        )}
        {state === "skipped" && <span className="text-muted-foreground">–</span>}
        {state === "pending" && <span className="w-2 h-2 rounded-full bg-muted-foreground/30" />}
      </span>
      <span className={state === "skipped" ? "text-muted-foreground" : ""}>
        {label}
        {state === "skipped" && skippedNote && (
          <span className="text-[10px] text-muted-foreground"> · {skippedNote}</span>
        )}
      </span>
    </div>
  );
}

function ProviderStep({
  presets,
  presetIdx,
  setPresetIdx,
  providerName,
  setProviderName,
  providerApiKey,
  setProviderApiKey,
  providerModel,
  setProviderModel,
  providerBaseUrl,
  setProviderBaseUrl,
  onProvisioned,
  error,
  testMsg,
  cloudMode,
  setCloudMode,
}: {
  presets: typeof PROVIDER_PRESETS;
  presetIdx: number;
  setPresetIdx: (i: number) => void;
  providerName: string;
  setProviderName: (s: string) => void;
  providerApiKey: string;
  setProviderApiKey: (s: string) => void;
  providerModel: string;
  setProviderModel: (s: string) => void;
  providerBaseUrl: string;
  setProviderBaseUrl: (s: string) => void;
  onProvisioned: () => void;
  error: string | null;
  testMsg: string | null;
  cloudMode: boolean;
  setCloudMode: (b: boolean) => void;
}) {
  const preset = presets[presetIdx];
  // Cloud-only preset picker. The local path is owned by OllamaDeployPanel.
  const cloudPresets = presets.filter((p) => p.kind !== "ollama");
  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-base font-semibold mb-1">
          Add a vision model <span className="text-muted-foreground font-normal">(optional)</span>
        </h3>
        <p className="text-xs text-muted-foreground leading-relaxed">
          Detection, faces, people and rules already work without this. A
          vision model adds plain-language scene captions and lets you Ask
          Nurby questions. Skip it now and add one anytime from Settings.
        </p>
      </div>
      {/* Lead with local AI. The panel auto-detects a reachable Ollama
          (local or on the Docker host), reuses an installed model, or
          pulls a RAM-appropriate one with progress. No key, fully local. */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium">Set up local AI</span>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-300">recommended</span>
        </div>
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          Runs on your own hardware via Ollama. Free, private, no API key.
        </p>
        <OllamaDeployPanel onProvisioned={onProvisioned} />
      </div>

      {/* Secondary path. a hosted provider for users without local hardware. */}
      <div className="pt-1 border-t border-border">
        <button
          type="button"
          onClick={() => setCloudMode(!cloudMode)}
          className="text-xs text-muted-foreground hover:text-foreground underline mt-3"
        >
          {cloudMode ? "Hide cloud providers" : "Or connect a cloud provider (OpenAI, Claude, Gemini)"}
        </button>
      </div>

      {cloudMode && (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2">
            {cloudPresets.map((p) => {
              const i = presets.indexOf(p);
              return (
                <button
                  key={p.kind}
                  type="button"
                  onClick={() => setPresetIdx(i)}
                  className={`text-left p-3 rounded-lg border transition-colors ${
                    presetIdx === i
                      ? "border-accent bg-accent/10"
                      : "border-border hover:border-muted-foreground"
                  }`}
                >
                  <div className="font-medium text-sm">{p.name}</div>
                  <p className="text-[11px] text-muted-foreground mt-0.5 leading-relaxed">
                    {p.hint}
                  </p>
                </button>
              );
            })}
          </div>
          <FieldRow label="Display name">
            <input
              type="text"
              value={providerName}
              onChange={(e) => setProviderName(e.target.value)}
              className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm focus:outline-none focus:border-accent"
            />
          </FieldRow>
          <FieldRow label="Base URL" hint="Auto-filled from preset">
            <input
              type="text"
              value={providerBaseUrl}
              onChange={(e) => setProviderBaseUrl(e.target.value)}
              readOnly
              className="w-full px-3 py-2 rounded-md border border-border text-sm font-mono bg-muted/30 opacity-70"
            />
          </FieldRow>
          <FieldRow label="Model" hint="The model name the provider uses by default. Override here if you want a different one.">
            <input
              type="text"
              value={providerModel}
              onChange={(e) => setProviderModel(e.target.value)}
              placeholder={preset.default_model}
              className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm font-mono focus:outline-none focus:border-accent"
            />
          </FieldRow>
          {preset.keyRequired && (
            <FieldRow label="API key" hint="Stored encrypted on the server. Never sent to other providers.">
              <input
                type="password"
                value={providerApiKey}
                onChange={(e) => setProviderApiKey(e.target.value)}
                placeholder="sk-..."
                className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm font-mono focus:outline-none focus:border-accent"
              />
            </FieldRow>
          )}
          <div className="rounded-md border border-amber-500/25 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-300/90 leading-relaxed">
            Cloud providers bill per call. Nurby caps Ask-Nurby spend with a
            per-user daily budget (default $5/day, adjustable in Settings), and
            the perception pipeline only calls the model on real motion, so
            idle cameras cost nothing.
          </div>
        </div>
      )}

      {error && <div className="text-xs text-danger">{error}</div>}
      {testMsg && (
        <div
          className={`text-xs ${
            testMsg.startsWith("Connected")
              ? "text-emerald-400"
              : testMsg.startsWith("Testing")
              ? "text-muted-foreground"
              : "text-amber-400"
          }`}
        >
          {testMsg}
        </div>
      )}
    </div>
  );
}

function CameraStep({ onAdded }: { onAdded: () => void }) {
  const { authFetch } = useAuth();
  const [mode, setMode] = useState<"demo" | "own">("demo");
  const [demoBusy, setDemoBusy] = useState(false);
  const [demoError, setDemoError] = useState("");

  const useDemo = async () => {
    setDemoBusy(true);
    setDemoError("");
    try {
      const r = await authFetch("/api/cameras/demo", { method: "POST" });
      if (!r.ok) {
        setDemoError("Could not add the demo camera. You can add a real one instead.");
        return;
      }
      onAdded();
    } catch {
      setDemoError("Network error adding the demo camera.");
    } finally {
      setDemoBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-base font-semibold mb-1">Add your first camera</h3>
        <p className="text-xs text-muted-foreground">
          No camera yet? Start with the demo feed and see Nurby work in seconds. You can connect real cameras anytime.
        </p>
      </div>

      <div className="rounded-lg border border-accent/30 bg-accent/5 p-3 space-y-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium">Demo camera</span>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-accent/15 text-accent">recommended</span>
        </div>
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          Streams looping sample CCTV footage through the full pipeline, so you can watch detections, people, and rules with zero setup.
        </p>
        {demoError && <div className="text-[11px] text-red-400">{demoError}</div>}
        <button
          type="button"
          onClick={useDemo}
          disabled={demoBusy}
          className="px-3 py-1.5 text-xs rounded-md bg-accent text-accent-foreground font-medium hover:opacity-90 disabled:opacity-50"
        >
          {demoBusy ? "Adding." : "Use demo camera and continue"}
        </button>
      </div>

      <button
        type="button"
        onClick={() => setMode(mode === "own" ? "demo" : "own")}
        className="text-xs text-muted-foreground hover:text-foreground underline"
      >
        {mode === "own" ? "Hide" : "Or connect your own camera"}
      </button>

      {mode === "own" && (
        <div className="rounded-lg border border-border p-3">
          <AddCameraModal embedded onSuccess={onAdded} onClose={() => setMode("demo")} />
        </div>
      )}
    </div>
  );
}

function DoneStep({ onClose }: { onClose: () => void }) {
  return (
    <div className="space-y-4 text-center py-6">
      <div className="w-12 h-12 rounded-full bg-emerald-500/15 border border-emerald-500/40 flex items-center justify-center mx-auto">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="text-emerald-400">
          <polyline points="20 6 9 17 4 12" />
        </svg>
      </div>
      <h3 className="text-lg font-semibold">You&apos;re set</h3>
      <p className="text-xs text-muted-foreground max-w-md mx-auto leading-relaxed">
        Your camera is connected. Give it ~30 seconds. Nurby starts
        describing activity as soon as it sees motion, and the first
        observations will land on your timeline.
      </p>
      <div className="text-left max-w-md mx-auto space-y-2">
        <div className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">
          Two things worth doing next
        </div>
        <a
          href="/rules"
          className="flex items-start gap-3 rounded-md border border-border bg-card/40 px-3 py-2 hover:border-accent/50 transition-colors"
        >
          <span className="text-base leading-none">🔔</span>
          <span>
            <span className="block text-xs font-medium">Create your first rule</span>
            <span className="block text-[11px] text-muted-foreground leading-tight">
              Get a Telegram or email alert when something specific happens.
            </span>
          </span>
        </a>
        <a
          href="/ask"
          className="flex items-start gap-3 rounded-md border border-border bg-card/40 px-3 py-2 hover:border-accent/50 transition-colors"
        >
          <span className="text-base leading-none">💬</span>
          <span>
            <span className="block text-xs font-medium">Ask Nurby anything</span>
            <span className="block text-[11px] text-muted-foreground leading-tight">
              &ldquo;What happened today?&rdquo; &middot; &ldquo;Was anyone at the door?&rdquo;
            </span>
          </span>
        </a>
      </div>
      <button
        type="button"
        onClick={onClose}
        className="px-4 py-2 text-sm rounded-md bg-accent text-accent-foreground font-medium hover:opacity-90"
      >
        Open dashboard
      </button>
    </div>
  );
}

function FieldRow({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="text-xs font-medium text-muted-foreground block mb-1">
        {label}
      </label>
      {children}
      {hint && <p className="text-[11px] text-muted-foreground mt-1">{hint}</p>}
    </div>
  );
}
