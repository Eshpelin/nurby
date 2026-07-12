// FastAPI returns `detail` as a string for app-level errors but as an
// array of { msg, loc } objects for 422 validation failures (and
// occasionally a bare object). Components that render `body?.detail`
// directly crash React ("Objects are not valid as a React child") on
// the array/object shapes. Route every API error message through this
// helper instead.
export function extractApiError(body: unknown, fallback: string): string {
  if (!body || typeof body !== "object") return fallback;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => (d && typeof d === "object" ? (d as { msg?: string }).msg : String(d)))
      .filter(Boolean);
    if (msgs.length) return msgs.join(". ");
  }
  if (detail && typeof detail === "object") {
    const msg = (detail as { msg?: string }).msg;
    if (typeof msg === "string") return msg;
  }
  return fallback;
}
