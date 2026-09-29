"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";
import { translate } from "@/lib/i18n";
import CameraBrandHelp from "@/components/CameraBrandHelp";
import { OllamaDeployPanel } from "@/components/OllamaDeployPanel";
import { AddCameraModal } from "@/components/AddCameraModal";
import { ONBOARDING_PRESETS } from "@/lib/provider-presets";
import { StorageLocationForm } from "@/components/settings/StorageLocation";
import {
  browserTimezone,
  markOnboardingDismissedLocally,
  recordFunnelEvent,
} from "@/lib/onboarding";
import { notifyProvidersChanged } from "@/lib/providers-changed";

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

type Step = "storage" | "choose" | "magic" | "camera" | "provider" | "done";

// Curated subset of the shared provider catalog (see @/lib/provider-presets).
const PROVIDER_PRESETS = ONBOARDING_PRESETS;


/**
 * First-run modal, ordered for the fastest path to a live feed:
 *   0. storage (where recordings live — #251. the first thing a new
 *      self-hoster wants to decide, and the last moment it is free of
 *      already-written data)
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
  const { authFetch, user } = useAuth();
  const t = (key: string, values?: Record<string, string | number>) => translate(user?.locale, key, values);
  // Welcome first (#293): the magic/manual choice is the promise of the
  // first visit, and the storage question only means something once a
  // path is picked. The manual path asks storage before any camera
  // writes video; the magic path skips it (the demo records nothing).
  const [step, setStep] = useState<Step>("choose");
  const [providers, setProviders] = useState<Provider[]>([]);
  // Detected once so the done step can offer the household timezone.
  const [browserTz] = useState(() => browserTimezone());
  // On by default: the browser timezone is almost always right, and the
  // checkbox is right there to untick. Only actually sent when ticked.
  const [tzAccepted, setTzAccepted] = useState(true);

  // Persist dismissal both locally (fast path) and server-side (so it
  // survives a browser/device change; an admin can re-trigger the wizard
  // by flipping onboarding_dismissed back to false in Settings).
  const markDismissed = useCallback(() => {
    markOnboardingDismissedLocally();
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
    notifyProvidersChanged();
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

  // Funnel counters (#293). Fire-and-forget; the aggregate feeds the admin
  // metrics card only.
  useEffect(() => {
    recordFunnelEvent(authFetch, "wizard_shown");
  }, [authFetch]);

  const onMagicChosen = useCallback(() => {
    recordFunnelEvent(authFetch, "magic_clicked");
    setStep("magic");
  }, [authFetch]);

  const onManualChosen = useCallback(() => {
    recordFunnelEvent(authFetch, "manual_clicked");
    setStep("storage");
  }, [authFetch]);

  const finishWizard = useCallback(() => {
    recordFunnelEvent(authFetch, "wizard_completed");
    if (tzAccepted && browserTz) {
      // Offered on the done step; the server validates the name.
      authFetch("/api/system/settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ system_timezone: browserTz }),
      }).catch(() => undefined);
    }
    markDismissed();
    onComplete();
  }, [authFetch, tzAccepted, browserTz, markDismissed, onComplete]);

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
      notifyProvidersChanged();
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

  // Escape closes the wizard. During magic, first cancel any in-flight
  // model download (best-effort) so nothing keeps pulling in the dark.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      if (step === "magic") {
        authFetch("/api/ollama/deploy", { method: "DELETE" }).catch(() => {});
      }
      dismiss();
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
              {t("onboarding.setup_title")}
            </h2>
            {(step === "camera" || step === "provider" || step === "done") && (
              <span className="text-xs text-muted-foreground">
                Step {stepNumber(step)} of 3
              </span>
            )}
          </div>
          <button
            onClick={() => {
              if (step === "magic") {
                authFetch("/api/ollama/deploy", { method: "DELETE" }).catch(() => {});
              }
              dismiss();
            }}
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            {t("onboarding.skip")}
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-5">
          {step === "storage" && (
            <StorageStep onNext={() => setStep("camera")} />
          )}
          {step === "choose" && (
            <ChooseStep t={t} onMagic={onMagicChosen} onManual={onManualChosen} />
          )}
          {step === "magic" && (
            <MagicStep
              t={t}
              onDone={finishWizard}
              browserTz={browserTz}
              tzAccepted={tzAccepted}
              onTzAccepted={setTzAccepted}
              onFallback={() => setStep("camera")}
              onCloudFallback={() => {
                setCloudMode(true);
                setStep("provider");
              }}
            />
          )}
          {step === "camera" && (
            <CameraStep t={t} onAdded={() => setStep("provider")} />
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
              t={t}
              setCloudMode={(b) => {
                setCloudMode(b);
                // Default the cloud picker to OpenAI, not Ollama, since the
                // panel above already owns the local path.
                if (b && presetIdx === 0) setPresetIdx(1);
              }}
            />
          )}
          {step === "done" && (
            <DoneStep
              onClose={finishWizard}
              browserTz={browserTz}
              tzAccepted={tzAccepted}
              onTzAccepted={setTzAccepted}
              t={t}
            />
          )}
        </div>

        {step !== "choose" && step !== "magic" && step !== "camera" && (
        <div className="px-5 py-3 border-t border-border flex items-center justify-between">
          <button
            onClick={() => {
              if (step === "provider") setStep("camera");
              if (step === "storage") setStep("choose");
            }}
            className={`px-3 py-1.5 text-xs rounded-md border border-border hover:bg-muted ${
              step === "done" ? "invisible" : ""
            }`}
          >
            {t("onboarding.back")}
          </button>
          {step === "provider" && !cloudMode && (
            <button
              onClick={() => setStep("done")}
              className="px-4 py-1.5 text-xs rounded-md border border-border hover:bg-muted text-muted-foreground"
            >
              {t("onboarding.skip")}
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
                ? t("onboarding.adding_provider")
                : providerForceAdvance
                ? t("onboarding.continue_anyway")
                : t("onboarding.add_test")}
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

// Storage preamble (issue #251): where recordings live. Runs before any
// camera exists, so the choice costs nothing — no files to migrate, no
// recordings split across drives. Entirely skippable; the default keeps
// working and Settings -> Storage location revisits it later. The form
// renders its own heading, so this step adds none (issue #320: the two
// headings used to read as a duplicate).
function StorageStep({ onNext }: { onNext: () => void }) {
  return (
    <div className="space-y-5">
      <StorageLocationForm />

      <p className="text-xs text-muted-foreground rounded-md border border-border bg-muted/20 px-3 py-2">
        The demo camera in “Show me some magic” uses this default location. You can change it any time in Settings → Storage location.
      </p>

      <div className="flex items-center justify-between pt-1">
        <button
          type="button"
          onClick={onNext}
          className="px-4 py-2 text-sm rounded-md bg-accent text-black font-medium hover:bg-accent/90 transition-colors"
        >
          Continue
        </button>
        <p className="text-[11px] text-muted-foreground">
          You can change this later in Settings → Storage location.
        </p>
      </div>
    </div>
  );
}

// First fork. one-click "magic" that provisions everything locally, or the
// hands-on path for people who want to wire their own camera and model.
function ChooseStep({
  t,
  onMagic,
  onManual,
}: {
  t: (key: string, values?: Record<string, string | number>) => string;
  onMagic: () => void;
  onManual: () => void;
}) {
  return (
    <div className="space-y-5">
      <div>
        <h3 className="text-xl font-semibold">{t("onboarding.choose_title")}</h3>
        <p className="text-sm text-muted-foreground leading-relaxed mt-1">
          {t("onboarding.choose_body")}
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
            <span className="text-sm font-semibold">{t("onboarding.magic_title")}</span>
          </div>
          <p className="text-[12px] text-muted-foreground leading-relaxed">
            {t("onboarding.magic_body")}
          </p>
          <span className="inline-block mt-3 text-[11px] font-medium text-accent group-hover:underline">
            {t("onboarding.magic_action")}
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
            <span className="text-sm font-semibold">{t("onboarding.manual_title")}</span>
          </div>
          <p className="text-[12px] text-muted-foreground leading-relaxed">
            {t("onboarding.manual_body")}
          </p>
          <span className="inline-block mt-3 text-[11px] font-medium text-muted-foreground">
            {t("onboarding.manual_action")}
          </span>
        </button>
      </div>
    </div>
  );
}

// The magic. Provisions the demo camera, then handles local AI honestly:
// an explicit choice when no Ollama is found, real pull progress with a
// cancel button, and a summary of what was actually set up.
type MagicPhase =
  | "camera"        // adding the demo camera
  | "cameraError"   // demo camera failed. retry or go manual
  | "detect"        // probing for a local Ollama
  | "fork"          // no Ollama found. user picks a path
  | "pulling"       // model download in flight (cancellable)
  | "summary";      // what was provisioned + next steps

function MagicStep({
  t,
  onDone,
  onFallback,
  onCloudFallback,
  browserTz,
  tzAccepted,
  onTzAccepted,
}: {
  t: (key: string, values?: Record<string, string | number>) => string;
  onDone: () => void;
  onFallback: () => void;
  onCloudFallback: () => void;
  browserTz: string;
  tzAccepted: boolean;
  onTzAccepted: (v: boolean) => void;
}) {
  const { authFetch } = useAuth();
  const [phase, setPhase] = useState<MagicPhase>("camera");
  const [tasks, setTasks] = useState<{ camera: TaskState; vlm: TaskState }>({
    camera: "pending",
    vlm: "pending",
  });
  const [pullPct, setPullPct] = useState<number | null>(null);
  const [pullMsg, setPullMsg] = useState("");
  const [vlmNote, setVlmNote] = useState<string | null>(null);
  const [deployedModel, setDeployedModel] = useState<string | null>(null);
  const [fellBackFrom, setFellBackFrom] = useState<string | null>(null);
  // Why a fallback model is being tried, shown under the progress bar so
  // the switch is never silent (#304).
  const [fallbackNote, setFallbackNote] = useState<string | null>(null);
  // True when the deployed model was already on the machine (#304): the
  // summary says nothing was downloaded.
  const [alreadyInstalled, setAlreadyInstalled] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const startedRef = useRef(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const cancelledRef = useRef(false);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const addDemoCamera = useCallback(async () => {
    setPhase("camera");
    setError(null);
    setTasks((t) => ({ ...t, camera: "running" }));
    try {
      const r = await authFetch("/api/cameras/demo", { method: "POST" });
      if (!r.ok && r.status !== 409) throw new Error(String(r.status));
      setTasks((t) => ({ ...t, camera: "done" }));
      return true;
    } catch {
      setTasks((t) => ({ ...t, camera: "pending" }));
      setError(
        "Could not add the demo camera. It streams from nurby.ai, so this " +
          "usually means no internet access. Retry, or set up your own camera.",
      );
      setPhase("cameraError");
      return false;
    }
  }, [authFetch]);

  const finishWithoutVlm = useCallback((note: string) => {
    stopPolling();
    setTasks((t) => ({ ...t, vlm: "skipped" }));
    setVlmNote(note);
    setPhase("summary");
  }, [stopPolling]);

  // Poll the deploy job until it settles.
  const pollDeploy = useCallback(
    (model: string) => {
      stopPolling();
      pollRef.current = setInterval(async () => {
        if (cancelledRef.current) return;
        try {
          const r = await authFetch("/api/ollama/deploy/status");
          const s = await r.json().catch(() => ({}));
          if (s.stage === "pulling" || s.stage === "registering") {
            setPullPct(typeof s.progress === "number" ? s.progress : null);
            setPullMsg(s.message || `Downloading ${model}`);
          } else if (s.stage === "done") {
            stopPolling();
            setDeployedModel(s.model || model);
            setTasks((t) => ({ ...t, vlm: "done" }));
            setPhase("summary");
          } else if (s.stage === "cancelled") {
            finishWithoutVlm("Download cancelled. Resume anytime from Settings; finished layers are kept.");
          } else if (s.stage === "error" || s.stage === "idle") {
            stopPolling();
            // Fall back once to a small proven model, then give up honestly.
            if (model !== "gemma3:4b") {
              setFellBackFrom(model);
              setFallbackNote(
                `This Ollama install can't run ${model} — trying Gemma 3 4B instead`,
              );
              startDeploy("gemma3:4b");
            } else {
              finishWithoutVlm(s.message || "Model download failed. Set up AI later from Settings.");
            }
          }
        } catch {
          /* transient poll failure. keep polling */
        }
      }, 2000);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [authFetch, stopPolling, finishWithoutVlm],
  );

  const startDeploy = useCallback(
    async (model: string) => {
      setPhase("pulling");
      setPullPct(null);
      setPullMsg(`Starting download of ${model}`);
      setTasks((t) => ({ ...t, vlm: "running" }));
      try {
        const dr = await authFetch("/api/ollama/deploy", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model }),
        });
        const data = await dr.json().catch(() => ({}));
        if (dr.ok && data.stage === "done") {
          setDeployedModel(data.model || model);
          setAlreadyInstalled(!!data.already_installed);
          setTasks((t) => ({ ...t, vlm: "done" }));
          setPhase("summary");
          return;
        }
        if (dr.ok && data.stage === "pulling") {
          // The server's message carries the catalog size ("Downloading
          // gemma3:4b (about 3.3 GB)") — show it instead of our guess.
          if (data.message) setPullMsg(data.message);
          pollDeploy(model);
          return;
        }
        // Preflight failures (disk/RAM) or no-ollama: try the light model
        // once when the problem is resources, otherwise stop honestly.
        if (data.code === "insufficient_ram" || data.code === "insufficient_disk") {
          if (model !== "gemma3:1b") {
            setFellBackFrom(model);
            startDeploy("gemma3:1b");
            return;
          }
        }
        finishWithoutVlm(data.message || "Could not start the model download.");
      } catch {
        finishWithoutVlm("Could not reach the server to start the download.");
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [authFetch, pollDeploy, finishWithoutVlm],
  );

  const cancelPull = useCallback(async () => {
    try {
      await authFetch("/api/ollama/deploy", { method: "DELETE" });
    } catch {
      /* the poll notices either way */
    }
    finishWithoutVlm("Download cancelled. Resume anytime from Settings; finished layers are kept.");
  }, [authFetch, finishWithoutVlm]);

  const detectAndDeploy = useCallback(async () => {
    setPhase("detect");
    setTasks((t) => ({ ...t, vlm: "running" }));
    let reachable = false;
    let model = "gemma3:4b";
    try {
      const sr = await authFetch("/api/ollama/status");
      if (sr.ok) {
        const s = await sr.json();
        reachable = !!(s.installed || s.running);
        model = s.recommended_model || model;
        if (s.recommended_installed) setAlreadyInstalled(true);
      }
    } catch {
      /* treat as no local AI */
    }
    if (reachable) {
      startDeploy(model);
    } else {
      setTasks((t) => ({ ...t, vlm: "pending" }));
      setPhase("fork");
    }
  }, [authFetch, startDeploy]);

  // Run once per mount (guards strict-mode double-invoke).
  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    (async () => {
      const ok = await addDemoCamera();
      if (ok) detectAndDeploy();
    })();
    return () => {
      cancelledRef.current = true;
      stopPolling();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const busy = phase === "camera" || phase === "detect";

  return (
    <div className="space-y-5 py-2">
      <div className="text-center space-y-1">
        <div className="text-3xl">✨</div>
        <h3 className="text-lg font-semibold">
          {phase === "summary" ? t("onboarding.magic_summary") : t("onboarding.magic_working")}
        </h3>
        {busy && (
          <p className="text-xs text-muted-foreground">
            {t("onboarding.magic_busy")}
          </p>
        )}
      </div>

      {/* Task checklist */}
      <div className="space-y-2">
        <MagicTaskRow state={tasks.camera} label={t("onboarding.task_camera")} />
        <MagicTaskRow
          state={tasks.vlm}
          label={t("onboarding.task_vlm")}
          skippedNote={vlmNote || t("onboarding.skipped")}
        />
      </div>

      {/* Demo camera failed: retry or go manual. No auto-teleport. */}
      {phase === "cameraError" && (
        <div className="space-y-3">
          <div className="text-[11px] text-amber-400 bg-amber-500/10 border border-amber-500/30 rounded-md px-2.5 py-1.5">
            {error}
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={async () => {
                const ok = await addDemoCamera();
                if (ok) detectAndDeploy();
              }}
              className="px-3 py-1.5 text-xs rounded-md bg-accent text-accent-foreground font-medium hover:opacity-90"
            >
              {t("onboarding.retry")}
            </button>
            <button
              type="button"
              onClick={onFallback}
              className="px-3 py-1.5 text-xs rounded-md border border-border hover:bg-muted"
            >
              {t("onboarding.manual_camera")}
            </button>
          </div>
        </div>
      )}

      {/* No local AI found: an explicit choice instead of a silent skip. */}
      {phase === "fork" && (
        <div className="space-y-2">
          <p className="text-xs text-muted-foreground">
            {t("onboarding.no_local_ai")}
          </p>
          <div className="rounded-md border border-border p-3 space-y-1">
            <div className="text-xs font-medium">{t("onboarding.install_ollama")}</div>
            <p className="text-[11px] text-muted-foreground leading-relaxed">
              {t("onboarding.ollama_help")} {" "}
              <a href="https://ollama.com/download" target="_blank" rel="noreferrer" className="underline">
                ollama.com/download
              </a>
              , {t("onboarding.ollama_or_start")} {" "}
              <code className="font-mono bg-muted px-1 rounded">docker compose --profile local-ai up -d ollama</code>.
              {t("onboarding.ollama_recheck_hint")}
            </p>
            <button
              type="button"
              onClick={detectAndDeploy}
              className="mt-1 px-3 py-1 text-[11px] rounded-md border border-border hover:bg-muted"
            >
              {t("onboarding.recheck_ollama")}
            </button>
          </div>
          <button
            type="button"
            onClick={onCloudFallback}
            className="w-full text-left rounded-md border border-border p-3 hover:border-accent transition-colors"
          >
            <div className="text-xs font-medium">{t("onboarding.use_cloud")}</div>
            <p className="text-[11px] text-muted-foreground">{t("onboarding.cloud_help")}</p>
          </button>
          <button
            type="button"
            onClick={() =>
              finishWithoutVlm(
                "Skipped by choice. Scene descriptions and Ask Nurby are off; " +
                  "detection, faces, recording and rules all work.",
              )
            }
            className="w-full text-left rounded-md border border-border p-3 hover:border-accent transition-colors"
          >
            <div className="text-xs font-medium">{t("onboarding.continue_without_ai")}</div>
            <p className="text-[11px] text-muted-foreground">{t("onboarding.no_ai_help")}</p>
          </button>
        </div>
      )}

      {/* Real pull progress with a cancel button. */}
      {phase === "pulling" && (
        <div className="space-y-2">
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-muted-foreground">{pullMsg}</span>
            <span className="font-mono font-medium">
              {pullPct != null ? `${Math.round(pullPct)}%` : "…"}
            </span>
          </div>
          <div className="h-2 rounded-full bg-muted overflow-hidden">
            <div
              className={`h-full bg-accent transition-[width] duration-700 ease-out ${pullPct == null ? "animate-pulse w-1/4" : ""}`}
              style={pullPct != null ? { width: `${pullPct}%` } : undefined}
            />
          </div>
          {fallbackNote && (
            <p className="text-[11px] text-amber-400">{fallbackNote}</p>
          )}
          <div className="flex items-center justify-between">
            <p className="text-[11px] text-muted-foreground">
              {fallbackNote ? t("onboarding.cancel_keeps_layers") : t("onboarding.download_minutes")}
            </p>
            <button
              type="button"
              onClick={cancelPull}
              className="px-3 py-1 text-[11px] rounded-md border border-border hover:bg-muted"
            >
              {t("onboarding.cancel")}
            </button>
          </div>
        </div>
      )}

      {/* Summary: what actually got provisioned, and what's next. */}
      {phase === "summary" && (
        <div className="space-y-3">
          <div className="rounded-md border border-border p-3 space-y-1.5 text-xs">
            <div>{t("onboarding.demo_summary")}</div>
            {deployedModel ? (
              <div>
                {t("onboarding.local_ai")} <span className="font-mono">{deployedModel}</span>
                {alreadyInstalled && !fellBackFrom && (
                  <span className="text-muted-foreground"> {t("onboarding.already_installed")}</span>
                )}
                {fellBackFrom && (
                  <span className="text-muted-foreground"> {t("onboarding.fell_back", { model: fellBackFrom })}</span>
                )}
                . {t("onboarding.runs_local")}
              </div>
            ) : (
              <div className="text-muted-foreground">
                {t("onboarding.no_model")} {vlmNote}
              </div>
            )}
          </div>
          {browserTz && (
            <label className="flex items-start gap-2.5 rounded-md border border-border bg-card/40 px-3 py-2 cursor-pointer hover:border-accent/40 transition-colors text-left">
              <input
                type="checkbox"
                checked={tzAccepted}
                onChange={(e) => onTzAccepted(e.target.checked)}
                className="mt-0.5 accent-green-500"
              />
              <span>
                <span className="block text-xs font-medium">Use {browserTz} as the Nurby timezone</span>
                <span className="block text-[11px] text-muted-foreground leading-tight">
                  Detected from this browser, so recaps and schedules run in your local time. Change later in Settings.
                </span>
              </span>
            </label>
          )}
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onDone}
              className="px-4 py-2 text-sm rounded-md bg-accent text-accent-foreground font-medium hover:opacity-90"
            >
              Open dashboard
            </button>
            <a
              href="/rules/new?template=package-at-door"
              className="text-xs text-muted-foreground hover:text-foreground underline"
            >
              Create your first alert
            </a>
          </div>
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
  t,
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
  t: (key: string, values?: Record<string, string | number>) => string;
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
          {t("onboarding.provider_title")} <span className="text-muted-foreground font-normal">({t("onboarding.optional")})</span>
        </h3>
        <p className="text-xs text-muted-foreground leading-relaxed">
          {t("onboarding.provider_body")}
        </p>
      </div>
      {/* Lead with local AI. The panel auto-detects a reachable Ollama
          (local or on the Docker host), reuses an installed model, or
          pulls a RAM-appropriate one with progress. No key, fully local. */}
      <div className="space-y-1.5">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium">{t("onboarding.local_ai_title")}</span>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-300">{t("onboarding.local_ai_recommended")}</span>
        </div>
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          {t("onboarding.local_ai_body")}
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
          {cloudMode ? t("onboarding.hide_cloud") : t("onboarding.connect_cloud")}
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
          <FieldRow label={t("onboarding.display_name")}>
            <input
              type="text"
              value={providerName}
              onChange={(e) => setProviderName(e.target.value)}
              className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm focus:outline-none focus:border-accent"
            />
          </FieldRow>
          <FieldRow label={t("onboarding.base_url")} hint={t("onboarding.base_url_hint")}>
            <input
              type="text"
              value={providerBaseUrl}
              onChange={(e) => setProviderBaseUrl(e.target.value)}
              readOnly
              className="w-full px-3 py-2 rounded-md border border-border text-sm font-mono bg-muted/30 opacity-70"
            />
          </FieldRow>
          <FieldRow label={t("onboarding.model")} hint={t("onboarding.model_hint")}>
            <input
              type="text"
              value={providerModel}
              onChange={(e) => setProviderModel(e.target.value)}
              placeholder={preset.default_model}
              className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm font-mono focus:outline-none focus:border-accent"
            />
          </FieldRow>
          {preset.keyRequired && (
            <FieldRow label={t("onboarding.api_key")} hint={t("onboarding.api_key_hint")}>
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
            {t("onboarding.cloud_budget")}
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

function CameraStep({ t, onAdded }: { t: (key: string, values?: Record<string, string | number>) => string; onAdded: () => void }) {
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
        setDemoError(t("onboarding.demo_error"));
        return;
      }
      onAdded();
    } catch {
      setDemoError(t("onboarding.demo_network_error"));
    } finally {
      setDemoBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-base font-semibold mb-1">{t("onboarding.camera_title")}</h3>
        <p className="text-xs text-muted-foreground">
          {t("onboarding.camera_body")}
        </p>
      </div>

      <div className="rounded-lg border border-accent/30 bg-accent/5 p-3 space-y-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium">{t("onboarding.demo_camera")}</span>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-accent/15 text-accent">{t("onboarding.recommended")}</span>
        </div>
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          {t("onboarding.demo_body")}
        </p>
        {demoError && <div className="text-[11px] text-red-400">{demoError}</div>}
        <button
          type="button"
          onClick={useDemo}
          disabled={demoBusy}
          className="px-3 py-1.5 text-xs rounded-md bg-accent text-accent-foreground font-medium hover:opacity-90 disabled:opacity-50"
        >
          {demoBusy ? t("onboarding.adding") : t("onboarding.use_demo")}
        </button>
      </div>

      <button
        type="button"
        onClick={() => setMode(mode === "own" ? "demo" : "own")}
        className="text-xs text-muted-foreground hover:text-foreground underline"
      >
        {mode === "own" ? t("onboarding.hide") : t("onboarding.connect_camera")}
      </button>

      {mode === "own" && (
        <div className="rounded-lg border border-border p-3">
          <AddCameraModal embedded onSuccess={onAdded} onClose={() => setMode("demo")} />
        </div>
      )}
    </div>
  );
}

function DoneStep({
  t,
  onClose,
  browserTz,
  tzAccepted,
  onTzAccepted,
}: {
  t: (key: string, values?: Record<string, string | number>) => string;
  onClose: () => void;
  browserTz: string;
  tzAccepted: boolean;
  onTzAccepted: (v: boolean) => void;
}) {
  return (
    <div className="space-y-4 text-center py-6">
      <div className="w-12 h-12 rounded-full bg-emerald-500/15 border border-emerald-500/40 flex items-center justify-center mx-auto">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="text-emerald-400">
          <polyline points="20 6 9 17 4 12" />
        </svg>
      </div>
      <h3 className="text-lg font-semibold">{t("onboarding.done_title")}</h3>
      <p className="text-xs text-muted-foreground max-w-md mx-auto leading-relaxed">{t("onboarding.done_body")}</p>
      {browserTz && (
        <label className="text-left max-w-md mx-auto flex items-start gap-2.5 rounded-md border border-border bg-card/40 px-3 py-2 cursor-pointer hover:border-accent/40 transition-colors">
          <input
            type="checkbox"
            checked={tzAccepted}
            onChange={(e) => onTzAccepted(e.target.checked)}
            className="mt-0.5 accent-green-500"
          />
          <span>
            <span className="block text-xs font-medium">{t("onboarding.use_timezone", { timezone: browserTz })}</span>
            <span className="block text-[11px] text-muted-foreground leading-tight">{t("onboarding.timezone_hint")}</span>
          </span>
        </label>
      )}
      <div className="text-left max-w-md mx-auto space-y-2">
        <div className="text-[11px] font-medium text-muted-foreground uppercase tracking-wide">
          {t("onboarding.next_title")}
        </div>
        <a
          href="/rules/new?template=package-at-door"
          className="flex items-start gap-3 rounded-md border border-border bg-card/40 px-3 py-2 hover:border-accent/50 transition-colors"
        >
          <span className="text-base leading-none">🔔</span>
          <span>
            <span className="block text-xs font-medium">{t("onboarding.first_alert")}</span>
            <span className="block text-[11px] text-muted-foreground leading-tight">{t("onboarding.first_alert_hint")}</span>
          </span>
        </a>
        <a
          href="/ask"
          className="flex items-start gap-3 rounded-md border border-border bg-card/40 px-3 py-2 hover:border-accent/50 transition-colors"
        >
          <span className="text-base leading-none">💬</span>
          <span>
            <span className="block text-xs font-medium">{t("onboarding.ask_anything")}</span>
            <span className="block text-[11px] text-muted-foreground leading-tight">{t("onboarding.ask_hint")}</span>
          </span>
        </a>
      </div>
      <button
        type="button"
        onClick={onClose}
        className="px-4 py-2 text-sm rounded-md bg-accent text-accent-foreground font-medium hover:opacity-90"
      >
        {t("onboarding.open_dashboard")}
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
