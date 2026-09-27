/** Small, typed catalog foundation for the first localization slice (#265). */

export type Locale = "en" | "es";

export const catalogs: Record<Locale, Record<string, string>> = {
  en: {
    "settings.language": "Language",
    "settings.language_help": "Choose the language used by Nurby on this account.",
    "settings.language_saved": "Language saved.",
  },
  es: {
    "settings.language": "Idioma",
    "settings.language_help": "Elige el idioma que Nurby usará en esta cuenta.",
    "settings.language_saved": "Idioma guardado.",
  },
};

export const supportedLocales: { value: Locale; label: string }[] = [
  { value: "en", label: "English" },
  { value: "es", label: "Español" },
];

export function translate(locale: Locale | string | null | undefined, key: string, values: Record<string, string | number> = {}): string {
  const catalog = catalogs[(locale as Locale) in catalogs ? locale as Locale : "en"];
  const fallback = catalogs.en[key] ?? key;
  return (catalog[key] ?? fallback).replace(/\{(\w+)\}/g, (_match, name: string) => String(values[name] ?? `{${name}}`));
}

export function validateCatalogs(): {
  missingInLocale: Record<string, string[]>;
  unusedKeys: string[];
  placeholderMismatches: Record<string, string[]>;
} {
  const englishKeys = new Set(Object.keys(catalogs.en));
  const missingInLocale: Record<string, string[]> = {};
  const placeholderMismatches: Record<string, string[]> = {};
  const placeholders = (value: string): string[] =>
    [...value.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort();
  for (const locale of Object.keys(catalogs) as Locale[]) {
    if (locale === "en") continue;
    missingInLocale[locale] = [...englishKeys].filter((key) => !(key in catalogs[locale]));
    placeholderMismatches[locale] = [...englishKeys].filter((key) =>
      key in catalogs[locale] &&
      placeholders(catalogs.en[key]).join("\0") !== placeholders(catalogs[locale][key]).join("\0")
    );
  }
  // English is the source catalog, so there are no English keys that are
  // unused by definition. The field remains part of the contract so a build
  // validator can report extra keys when contributor packs are loaded later.
  return { missingInLocale, unusedKeys: [], placeholderMismatches };
}
