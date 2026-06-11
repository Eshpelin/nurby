"use client";

/**
 * App-wide action feedback: toasts and a promise-based confirm dialog.
 *
 * Before this, saves and deletes happened silently and every destructive
 * action was a one-click, no-undo affair. `useToast()` gives any component
 * a `toast.success/error/info(message)` call; `useConfirm()` returns an
 * `await confirm({...})` that resolves true/false, so a delete reads:
 *
 *   if (await confirm({ title: "Delete this rule?", danger: true })) { ... }
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";

// ── Toasts ───────────────────────────────────────────────────────────

type ToastKind = "success" | "error" | "info";
interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
}

interface ToastApi {
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

let _toastSeq = 0;

// ── Confirm dialog ───────────────────────────────────────────────────

interface ConfirmOptions {
  title: string;
  body?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
}

type ConfirmFn = (opts: ConfirmOptions) => Promise<boolean>;
const ConfirmContext = createContext<ConfirmFn | null>(null);

export function FeedbackProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const timers = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
    const t = timers.current.get(id);
    if (t) {
      clearTimeout(t);
      timers.current.delete(id);
    }
  }, []);

  const push = useCallback(
    (kind: ToastKind, message: string) => {
      const id = ++_toastSeq;
      setToasts((prev) => [...prev.slice(-3), { id, kind, message }]);
      timers.current.set(
        id,
        setTimeout(() => dismiss(id), kind === "error" ? 6000 : 3500)
      );
    },
    [dismiss]
  );

  const toastApi = useRef<ToastApi>({
    success: (m) => push("success", m),
    error: (m) => push("error", m),
    info: (m) => push("info", m),
  });
  // Keep the closure's `push` current without changing the stable api object.
  toastApi.current.success = (m) => push("success", m);
  toastApi.current.error = (m) => push("error", m);
  toastApi.current.info = (m) => push("info", m);

  // Confirm state.
  const [confirmState, setConfirmState] = useState<
    (ConfirmOptions & { resolve: (v: boolean) => void }) | null
  >(null);

  const confirm = useCallback<ConfirmFn>((opts) => {
    return new Promise<boolean>((resolve) => {
      setConfirmState({ ...opts, resolve });
    });
  }, []);

  const settleConfirm = useCallback(
    (value: boolean) => {
      setConfirmState((cur) => {
        cur?.resolve(value);
        return null;
      });
    },
    []
  );

  // Escape / Enter for the confirm dialog.
  useEffect(() => {
    if (!confirmState) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") settleConfirm(false);
      if (e.key === "Enter") settleConfirm(true);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [confirmState, settleConfirm]);

  const kindStyles: Record<ToastKind, string> = {
    success: "border-green-500/40 bg-green-500/10 text-green-300",
    error: "border-red-500/40 bg-red-500/10 text-red-300",
    info: "border-border bg-card text-foreground",
  };
  const kindIcon: Record<ToastKind, string> = {
    success: "✓",
    error: "✕",
    info: "i",
  };

  return (
    <ToastContext.Provider value={toastApi.current}>
      <ConfirmContext.Provider value={confirm}>
        {children}

        {/* Toast stack */}
        <div
          className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2 max-w-[min(92vw,360px)]"
          aria-live="polite"
          role="status"
        >
          {toasts.map((t) => (
            <div
              key={t.id}
              className={`flex items-start gap-2 rounded-md border px-3 py-2 text-sm shadow-lg backdrop-blur ${kindStyles[t.kind]}`}
            >
              <span className="font-bold leading-5 flex-shrink-0">{kindIcon[t.kind]}</span>
              <span className="flex-1">{t.message}</span>
              <button
                type="button"
                onClick={() => dismiss(t.id)}
                aria-label="Dismiss"
                className="text-muted-foreground hover:text-foreground leading-5"
              >
                ×
              </button>
            </div>
          ))}
        </div>

        {/* Confirm dialog */}
        {confirmState && (
          <div className="fixed inset-0 z-[110] flex items-center justify-center">
            <div
              className="absolute inset-0 bg-black/60"
              onClick={() => settleConfirm(false)}
            />
            <div
              role="alertdialog"
              aria-modal="true"
              aria-label={confirmState.title}
              className="relative w-full max-w-sm mx-4 rounded-lg border border-border bg-card p-5 shadow-xl"
            >
              <h2 className="text-base font-semibold mb-1">{confirmState.title}</h2>
              {confirmState.body && (
                <p className="text-sm text-muted-foreground mb-4">{confirmState.body}</p>
              )}
              <div className="flex justify-end gap-2 mt-4">
                <button
                  type="button"
                  onClick={() => settleConfirm(false)}
                  className="px-3 py-1.5 text-sm rounded-md border border-border hover:bg-muted transition-colors"
                >
                  {confirmState.cancelLabel || "Cancel"}
                </button>
                <button
                  type="button"
                  autoFocus
                  onClick={() => settleConfirm(true)}
                  className={`px-3 py-1.5 text-sm rounded-md font-medium transition-colors ${
                    confirmState.danger
                      ? "bg-red-500 text-white hover:bg-red-600"
                      : "bg-foreground text-background hover:opacity-90"
                  }`}
                >
                  {confirmState.confirmLabel || (confirmState.danger ? "Delete" : "Confirm")}
                </button>
              </div>
            </div>
          </div>
        )}
      </ConfirmContext.Provider>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    // No-op fallback so a component outside the provider never crashes.
    return { success: () => {}, error: () => {}, info: () => {} };
  }
  return ctx;
}

export function useConfirm(): ConfirmFn {
  const ctx = useContext(ConfirmContext);
  if (!ctx) {
    return async () => window.confirm("Are you sure?");
  }
  return ctx;
}
