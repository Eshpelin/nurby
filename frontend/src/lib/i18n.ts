/** Small, typed catalog foundation for the first localization slice (#265). */

export type Locale = "en" | "es";

const catalogs: Record<Locale, Record<string, string>> = {
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

export function validateCatalogs(): { missingInLocale: Record<string, string[]>; unusedKeys: string[] } {
  const englishKeys = new Set(Object.keys(catalogs.en));
  const missingInLocale: Record<string, string[]> = {};
  for (const locale of Object.keys(catalogs) as Locale[]) {
    if (locale === "en") continue;
    missingInLocale[locale] = [...englishKeys].filter((key) => !(key in catalogs[locale]));
  }
  return { missingInLocale, unusedKeys: [] };
}
