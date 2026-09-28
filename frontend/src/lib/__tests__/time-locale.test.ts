import { describe, expect, it } from "vitest";
import { formatCount, formatNumber, getDisplayLocale, setDisplayLocale, timeAgo } from "@/lib/time";

describe("locale-aware shared formatting", () => {
  it("updates the selected display locale", () => {
    setDisplayLocale("es");
    expect(getDisplayLocale()).toBe("es");
  });

  it("formats numbers and plural categories using the active locale", () => {
    setDisplayLocale("es");
    expect(formatNumber(1234567)).toBe("1.234.567");
    expect(formatCount(1, "alert", "alerts")).toBe("1 alert");
    expect(formatCount(2, "alert", "alerts")).toBe("2 alerts");
  });

  it("localizes relative-time buckets", () => {
    setDisplayLocale("es");
    expect(timeAgo(new Date().toISOString())).toBe("ahora mismo");
    expect(timeAgo(new Date(Date.now() - 2 * 60 * 1000).toISOString())).toMatch(/hace 2/);
    setDisplayLocale("en");
    expect(timeAgo(new Date().toISOString())).toBe("just now");
  });
});
