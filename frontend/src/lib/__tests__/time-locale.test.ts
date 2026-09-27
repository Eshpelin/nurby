import { describe, expect, it } from "vitest";
import { formatCount, formatNumber, getDisplayLocale, setDisplayLocale } from "@/lib/time";

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
});
