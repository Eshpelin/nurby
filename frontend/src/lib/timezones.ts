/** Shared timezone picker options (settings page, per-camera settings). */

export const COMMON_TIMEZONES = [
  "America/Los_Angeles", "America/Denver", "America/Chicago", "America/New_York",
  "America/Toronto", "America/Vancouver", "America/Mexico_City", "America/Sao_Paulo",
  "Europe/London", "Europe/Berlin", "Europe/Paris", "Europe/Amsterdam",
  "Europe/Madrid", "Europe/Athens", "Europe/Moscow",
  "Africa/Cairo", "Africa/Johannesburg",
  "Asia/Dubai", "Asia/Karachi", "Asia/Kolkata", "Asia/Dhaka",
  "Asia/Bangkok", "Asia/Singapore", "Asia/Shanghai", "Asia/Tokyo", "Asia/Seoul",
  "Australia/Sydney", "Australia/Melbourne", "Pacific/Auckland", "UTC",
];

/**
 * The picker list with the browser's own timezone first, so users find
 * their local zone without scrolling, even when it is not in the common set.
 */
export function timezoneOptions(): string[] {
  let local: string | undefined;
  try {
    local = Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    // Older browsers without Intl timezone support.
  }
  if (!local) return [...COMMON_TIMEZONES];
  return [local, ...COMMON_TIMEZONES.filter((tz) => tz !== local)];
}
