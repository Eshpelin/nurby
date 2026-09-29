import { catalogs, translate, validateCatalogs } from "@/lib/i18n";
import { describe, expect, it } from "vitest";

describe("translation catalogs", () => {
  it("have no missing keys or interpolation mismatches", () => {
    const result = validateCatalogs();
    expect(Object.values(result.missingInLocale).flat()).toEqual([]);
    expect(Object.values(result.placeholderMismatches).flat()).toEqual([]);
    expect(result.unusedKeys).toEqual([]);
  });

  it("falls back to English and preserves an unresolved key visibly", () => {
    expect(translate("es", "settings.language")).toBe(catalogs.es["settings.language"]);
    expect(translate("es", "settings.not_yet_translated")).toBe("settings.not_yet_translated");
  });

  it("keeps interpolation stable across locales", () => {
    catalogs.en["test.count"] = "{count} alert";
    catalogs.es["test.count"] = "{count} alerta";
    expect(translate("es", "test.count", { count: 3 })).toBe("3 alerta");
    delete catalogs.en["test.count"];
    delete catalogs.es["test.count"];
  });

  it("reports keys that exist only in a contributor locale", () => {
    catalogs.es["test.orphan"] = "Solo en español";
    expect(validateCatalogs().unusedKeys).toEqual(["es:test.orphan"]);
    delete catalogs.es["test.orphan"];
  });
});
