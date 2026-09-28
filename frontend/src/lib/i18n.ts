/** Small, typed catalog foundation for the first localization slice (#265). */

export type Locale = "en" | "es";

export const catalogs: Record<Locale, Record<string, string>> = {
  en: {
    "settings.language": "Language",
    "settings.language_help": "Choose the language used by Nurby on this account.",
    "settings.language_saved": "Language saved.",
    "nav.home": "Home",
    "nav.cameras": "Cameras",
    "nav.settings": "Settings",
    "nav.activity": "Activity",
    "nav.ask": "Ask",
    "nav.people": "People",
    "nav.everything": "Everything",
    "nav.alerts": "Alerts",
    "nav.incidents": "Incidents",
    "nav.journeys": "Journeys",
    "nav.conversations": "Conversations",
    "nav.recordings": "Recordings",
    "nav.memory": "Memory",
    "nav.scheduled_questions": "Scheduled questions",
    "nav.vehicles": "Vehicles",
    "wizard.title": "Set up Nurby",
    "wizard.close": "Close",
    "wizard.step": "Step {step} of {total}",
    "wizard.loading": "Loading your setup…",
    "wizard.skip": "Skip this step for now",
    "wizard.later": "Do this later",
    "wizard.continue": "Continue",
    "wizard.back": "Back",
    "wizard.goal_title": "What should Nurby watch for first?",
    "wizard.goal_help": "Pick one goal. You can add more later. Choosing a goal changes nothing on its own.",
    "wizard.place": "Where are you using Nurby?",
    "wizard.home": "Home",
    "wizard.business": "Small business",
    "wizard.goal": "Goal",
    "wizard.place_name": "Name this place (optional)",
    "wizard.create": "Create the draft rule",
    "wizard.creating": "Creating…",
    "wizard.rule_title": "Set up the rule",
    "wizard.test_title": "Trigger a real event",
    "wizard.confirm_title": "Confirm the clip",
    "events.title": "Review",
    "events.export_csv": "Export CSV",
    "events.select_page": "Select page",
    "events.alerts": "Alerts",
    "events.detections": "Detections",
    "events.everything": "Everything",
    "events.tier_help": "Alerts are the push-worthy tier; detections are kept for review.",
    "events.all_cameras": "All cameras",
    "events.all_rules": "All rules",
    "events.reviewed_and_unreviewed": "Reviewed + unreviewed",
    "events.unreviewed_only": "Unreviewed only",
    "events.reviewed_only": "Reviewed only",
    "events.loading": "Loading alerts.",
    "events.empty": "No alerts match these filters. When a rule fires, it lands here.",
    "events.load_more": "Load more",
    "events.reviewed": "Reviewed",
    "settings.alerts": "Alerts",
    "settings.alerts_help": "What should I be told about?",
    "settings.alert_rules": "Alert rules",
    "settings.scheduled_questions": "Scheduled questions",
    "settings.expected_activity": "Expected activity",
  },
  es: {
    "settings.language": "Idioma",
    "settings.language_help": "Elige el idioma que Nurby usará en esta cuenta.",
    "settings.language_saved": "Idioma guardado.",
    "nav.home": "Inicio",
    "nav.cameras": "Cámaras",
    "nav.settings": "Configuración",
    "nav.activity": "Actividad",
    "nav.ask": "Preguntar",
    "nav.people": "Personas",
    "nav.everything": "Todo",
    "nav.alerts": "Alertas",
    "nav.incidents": "Incidentes",
    "nav.journeys": "Recorridos",
    "nav.conversations": "Conversaciones",
    "nav.recordings": "Grabaciones",
    "nav.memory": "Memoria",
    "nav.scheduled_questions": "Preguntas programadas",
    "nav.vehicles": "Vehículos",
    "wizard.title": "Configura Nurby",
    "wizard.close": "Cerrar",
    "wizard.step": "Paso {step} de {total}",
    "wizard.loading": "Cargando tu configuración…",
    "wizard.skip": "Omitir este paso por ahora",
    "wizard.later": "Hacerlo más tarde",
    "wizard.continue": "Continuar",
    "wizard.back": "Atrás",
    "wizard.goal_title": "¿Qué debería vigilar Nurby primero?",
    "wizard.goal_help": "Elige un objetivo. Puedes añadir más después. Elegir un objetivo no cambia nada por sí solo.",
    "wizard.place": "¿Dónde usas Nurby?",
    "wizard.home": "Casa",
    "wizard.business": "Pequeño negocio",
    "wizard.goal": "Objetivo",
    "wizard.place_name": "Nombra este lugar (opcional)",
    "wizard.create": "Crear regla borrador",
    "wizard.creating": "Creando…",
    "wizard.rule_title": "Configura la regla",
    "wizard.test_title": "Activa un evento real",
    "wizard.confirm_title": "Confirma el clip",
    "events.title": "Revisión",
    "events.export_csv": "Exportar CSV",
    "events.select_page": "Seleccionar página",
    "events.alerts": "Alertas",
    "events.detections": "Detecciones",
    "events.everything": "Todo",
    "events.tier_help": "Las alertas requieren atención; las detecciones se conservan para revisión.",
    "events.all_cameras": "Todas las cámaras",
    "events.all_rules": "Todas las reglas",
    "events.reviewed_and_unreviewed": "Revisadas y sin revisar",
    "events.unreviewed_only": "Solo sin revisar",
    "events.reviewed_only": "Solo revisadas",
    "events.loading": "Cargando alertas.",
    "events.empty": "Ninguna alerta coincide con estos filtros. Cuando se activa una regla, aparece aquí.",
    "events.load_more": "Cargar más",
    "events.reviewed": "Revisada",
    "settings.alerts": "Alertas",
    "settings.alerts_help": "¿Sobre qué debería recibir avisos?",
    "settings.alert_rules": "Reglas de alerta",
    "settings.scheduled_questions": "Preguntas programadas",
    "settings.expected_activity": "Actividad esperada",
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
