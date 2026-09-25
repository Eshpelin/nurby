export const PROVIDERS_CHANGED_EVENT = "nurby:providers-changed";

export function notifyProvidersChanged(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(PROVIDERS_CHANGED_EVENT));
  }
}
