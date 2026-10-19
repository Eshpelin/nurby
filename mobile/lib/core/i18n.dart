/// Typed translation catalog for the mobile app (#265).
///
/// Mirrors the web catalog in `frontend/src/lib/i18n.ts`: English is the
/// source catalog, every supported locale must carry the same keys and the
/// same `{named}` interpolation placeholders, and lookup falls back
/// locale -> English -> the key itself so a missing translation shows the
/// key to maintainers instead of rendering an empty control.
///
/// Keys are shared with the web catalog where the concept exists on both
/// platforms (`nav.*`, `common.*`, `settings.language`) so wording stays
/// consistent across the product.
library;

import 'package:flutter/material.dart';

/// Locales shipped with the app. Adding a language means adding a catalog
/// below, an enum entry, and contract-test coverage — nothing else.
enum AppLocale {
  en('en', 'English'),
  es('es', 'Español');

  const AppLocale(this.code, this.label);
  final String code;
  final String label;

  static AppLocale? fromLanguageCode(String? code) {
    if (code == null) return null;
    for (final locale in values) {
      if (locale.code == code) return locale;
    }
    return null;
  }
}

const Map<String, String> _catalogEn = {
  // -- Shared across surfaces ------------------------------------------------
  'common.cancel': 'Cancel',
  'common.delete': 'Delete',
  'common.retry': 'Retry',
  'common.loading': 'Loading…',
  'common.offline_banner': 'Offline — showing cached data',

  // -- Bottom navigation shell ------------------------------------------------
  'nav.home': 'Home',
  'nav.cameras': 'Cameras',
  'nav.activity': 'Activity',
  'nav.ask': 'Ask',
  'nav.people': 'People',
  'nav.settings': 'Settings',
  'common.search': 'Search',
  'shell.enable_notifications_title': 'Enable notifications?',
  'shell.enable_notifications_body':
      'Nurby can alert you when rules fire, even while the app is in '
      'the background.',
  'shell.not_now': 'Not now',
  'shell.enable': 'Enable',

  // -- Push notifications (no build context available) ------------------------
  'push.new_notification': 'New notification',
  'push.alert_title': 'Nurby alert',
  'push.rule_fired': 'A rule fired',
  'push.camera_prefix': 'Camera: {camera}',

  // -- Server address (first run) ----------------------------------------------
  'server.subtitle': 'Connect to your self-hosted Nurby server',
  'server.address': 'Server address',
  'server.error_save': 'Could not save server address',
  'server.connect': 'Connect',
  'server.scan_qr': 'Scan QR code',
  'server.find_code': 'Find the code in the web app under Settings.',

  // -- Login / setup -------------------------------------------------------
  'login.title': 'Sign in',
  'login.email': 'Email',
  'login.password': 'Password',
  'login.sign_in': 'Sign in',
  'login.scan_qr': 'Scan QR code',
  'login.change_server': 'Change server',
  'setup.title': 'Create admin account',
  'setup.subtitle':
      'This Nurby server has no users yet. Create the first admin.',
  'setup.display_name': 'Display name',
  'setup.create_account': 'Create account',

  // -- QR pairing ------------------------------------------------------------
  'qr.title': 'Scan QR code',
  'qr.hint':
      'In the web app, open Settings and tap "Mobile app" to show a pairing '
      'code.',
  'qr.invalid': 'Not a Nurby pairing code',
  'qr.failed':
      'Pairing failed. The code may have expired; generate a new one and try '
      'again.',

  // -- Settings hub -------------------------------------------------------
  'settings.title': 'Settings',
  'settings_hub.section_alerts': 'Alerts',
  'settings_hub.section_sharing': 'Sharing',
  'settings_hub.section_household_ai': 'Household and AI',
  'settings_hub.section_admin': 'Admin',
  'settings_hub.review_center': 'Review Center',
  'settings_hub.review_center_hint':
      'Incidents, alerts, and identity suggestions',
  'settings_hub.alert_rules': 'Alert rules',
  'settings_hub.alert_rules_hint': 'What should I be told about',
  'settings_hub.notifications': 'Notifications',
  'settings_hub.notifications_hint': 'What has been sent to this phone',
  'settings_hub.scheduled_questions': 'Scheduled questions',
  'settings_hub.scheduled_questions_hint': 'Questions answered on a clock',
  'settings_hub.guardians': 'Guardians',
  'settings_hub.guardians_hint': 'Who can watch someone in this household',
  'settings_hub.share_links': 'Share links',
  'settings_hub.share_links_hint': 'Links you have sent out',
  'settings_hub.household_ai': 'Household, AI models, privacy',
  'settings_hub.household_ai_hint': 'Blur, detection defaults, recaps, models',
  'settings_hub.who_sees_cameras': 'Who sees which cameras',
  'settings_hub.who_sees_cameras_hint': 'Per-person camera access',
  'settings_hub.ai_backlog': 'AI backlog',
  'settings_hub.ai_backlog_hint': 'Where the pipeline is',
  'settings_hub.everyones_questions': "Everyone's questions",
  'settings_hub.everyones_questions_hint': 'Every Ask run in the household',
  'settings_hub.sign_out': 'Sign out',

  // -- Language picker -----------------------------------------------------
  'settings.language': 'Language',
  'settings.language_help': 'Choose the language Nurby uses on this account.',
  'settings.language_system': 'System default',
  'settings.language_saved': 'Language saved.',

  // -- Home ----------------------------------------------------------------
  'home.cameras_online': '{online} of {total} cameras online',
  'home.see_all': 'See all',
  'home.needs_attention': 'Needs attention',
  'home.all_alerts': 'All alerts',
  'home.nothing_waiting': 'Nothing waiting for you.',
  'home.what_should_i_be_told': 'What should I be told about?',

  // -- Activity filter chips -------------------------------------------------
  'activity.kind_all': 'All',
  'activity.kind_alerts': 'Alerts',
  'activity.kind_sightings': 'Sightings',
  'activity.kind_incidents': 'Incidents',
  'activity.kind_journeys': 'Journeys',
  'activity.kind_conversations': 'Conversations',
  'activity.kind_recordings': 'Recordings',
  'activity.kind_recaps': 'Camera recaps',
};

const Map<String, String> _catalogEs = {
  'common.cancel': 'Cancelar',
  'common.delete': 'Eliminar',
  'common.retry': 'Reintentar',
  'common.loading': 'Cargando…',
  'common.offline_banner': 'Sin conexión: mostrando datos guardados',

  'nav.home': 'Inicio',
  'nav.cameras': 'Cámaras',
  'nav.activity': 'Actividad',
  'nav.ask': 'Preguntar',
  'nav.people': 'Personas',
  'nav.settings': 'Configuración',
  'common.search': 'Buscar',
  'shell.enable_notifications_title': '¿Activar notificaciones?',
  'shell.enable_notifications_body':
      'Nurby puede avisarte cuando se active una regla, incluso con la '
      'aplicación en segundo plano.',
  'shell.not_now': 'Ahora no',
  'shell.enable': 'Activar',

  'push.new_notification': 'Nueva notificación',
  'push.alert_title': 'Alerta de Nurby',
  'push.rule_fired': 'Se activó una regla',
  'push.camera_prefix': 'Cámara: {camera}',

  'server.subtitle': 'Conéctate a tu servidor de Nurby autoalojado',
  'server.address': 'Dirección del servidor',
  'server.error_save': 'No se pudo guardar la dirección del servidor',
  'server.connect': 'Conectar',
  'server.scan_qr': 'Escanear código QR',
  'server.find_code':
      'Encuentra el código en la aplicación web, en Configuración.',

  'login.title': 'Iniciar sesión',
  'login.email': 'Correo electrónico',
  'login.password': 'Contraseña',
  'login.sign_in': 'Iniciar sesión',
  'login.scan_qr': 'Escanear código QR',
  'login.change_server': 'Cambiar de servidor',
  'setup.title': 'Crear cuenta de administrador',
  'setup.subtitle':
      'Este servidor de Nurby aún no tiene usuarios. Crea el primer '
      'administrador.',
  'setup.display_name': 'Nombre para mostrar',
  'setup.create_account': 'Crear cuenta',

  'qr.title': 'Escanear código QR',
  'qr.hint':
      'En la aplicación web, abre Configuración y toca «Aplicación móvil» '
      'para mostrar un código de emparejamiento.',
  'qr.invalid': 'No es un código de emparejamiento de Nurby',
  'qr.failed':
      'No se pudo emparejar. El código puede haber caducado; genera uno '
      'nuevo y vuelve a intentarlo.',

  'settings.title': 'Configuración',
  'settings_hub.section_alerts': 'Alertas',
  'settings_hub.section_sharing': 'Compartir',
  'settings_hub.section_household_ai': 'Hogar e IA',
  'settings_hub.section_admin': 'Administración',
  'settings_hub.review_center': 'Centro de revisión',
  'settings_hub.review_center_hint': 'Incidentes, alertas y sugerencias de identidad',
  'settings_hub.alert_rules': 'Reglas de alerta',
  'settings_hub.alert_rules_hint': 'Qué debe avisarme',
  'settings_hub.notifications': 'Notificaciones',
  'settings_hub.notifications_hint': 'Qué se ha enviado a este teléfono',
  'settings_hub.scheduled_questions': 'Preguntas programadas',
  'settings_hub.scheduled_questions_hint': 'Preguntas respondidas a intervalos',
  'settings_hub.guardians': 'Personas a cargo',
  'settings_hub.guardians_hint': 'Quién puede vigilar a alguien de este hogar',
  'settings_hub.share_links': 'Enlaces para compartir',
  'settings_hub.share_links_hint': 'Enlaces que has enviado',
  'settings_hub.household_ai': 'Hogar, modelos de IA y privacidad',
  'settings_hub.household_ai_hint': 'Desenfoque, valores de detección, resúmenes y modelos',
  'settings_hub.who_sees_cameras': 'Quién ve cada cámara',
  'settings_hub.who_sees_cameras_hint': 'Acceso a cámaras por persona',
  'settings_hub.ai_backlog': 'Cola de IA',
  'settings_hub.ai_backlog_hint': 'En qué va el procesamiento',
  'settings_hub.everyones_questions': 'Preguntas de todos',
  'settings_hub.everyones_questions_hint': 'Cada consulta de Ask del hogar',
  'settings_hub.sign_out': 'Cerrar sesión',

  'settings.language': 'Idioma',
  'settings.language_help': 'Elige el idioma que Nurby usará en esta cuenta.',
  'settings.language_system': 'Predeterminado del sistema',
  'settings.language_saved': 'Idioma guardado.',

  'home.cameras_online': '{online} de {total} cámaras en línea',
  'home.see_all': 'Ver todas',
  'home.needs_attention': 'Requieren atención',
  'home.all_alerts': 'Todas las alertas',
  'home.nothing_waiting': 'Nada te está esperando.',
  'home.what_should_i_be_told': '¿Qué debe avisarme?',

  'activity.kind_all': 'Todo',
  'activity.kind_alerts': 'Alertas',
  'activity.kind_sightings': 'Avistamientos',
  'activity.kind_incidents': 'Incidentes',
  'activity.kind_journeys': 'Recorridos',
  'activity.kind_conversations': 'Conversaciones',
  'activity.kind_recordings': 'Grabaciones',
  'activity.kind_recaps': 'Resúmenes de cámara',
};

/// Provides the active locale to every [t] call below the navigator.
/// Widget tests that pump a single screen without the app shell simply
/// resolve to English.
class NurbyI18n extends InheritedWidget {
  const NurbyI18n({super.key, required this.locale, required super.child});

  final AppLocale locale;

  static AppLocale localeOf(BuildContext context) =>
      context
          .dependOnInheritedWidgetOfExactType<NurbyI18n>()
          ?.locale ??
      AppLocale.en;

  @override
  bool updateShouldNotify(NurbyI18n oldWidget) => oldWidget.locale != locale;
}

/// Translate [key] using the locale provided by the nearest [NurbyI18n].
String t(
  BuildContext context,
  String key, [
  Map<String, Object?> values = const {},
]) => translateLocale(NurbyI18n.localeOf(context), key, values);

/// Translate [key] for an explicit locale, for code without a build
/// context (push notifications, background work).
String translateLocale(
  AppLocale locale,
  String key, [
  Map<String, Object?> values = const {},
]) {
  final catalog = locale == AppLocale.en ? _catalogEn : _catalogEs;
  final fallback = _catalogEn[key] ?? key;
  return (catalog[key] ?? fallback).replaceAllMapped(
    RegExp(r'\{(\w+)\}'),
    (match) {
      final name = match.group(1)!;
      final value = values[name];
      // An unresolved placeholder stays visible, like the web catalog.
      return value != null ? value.toString() : '{$name}';
    },
  );
}

/// Resolve the effective locale: an explicit user choice wins, then the
/// device language when supported, then English.
AppLocale effectiveLocale(AppLocale? setting) {
  if (setting != null) return setting;
  final system = WidgetsBinding.instance.platformDispatcher.locale;
  return AppLocale.fromLanguageCode(system.languageCode) ?? AppLocale.en;
}

/// Contract check mirroring `validateCatalogs()` in the web catalog:
/// contributor locales must not drift from the English source.
({
  List<String> missingInLocale,
  List<String> unusedKeys,
  List<String> placeholderMismatches,
})
validateMobileCatalogs() =>
    validateCatalogPair(_catalogEn, _catalogEs);

/// Validate an English source catalog against a contributor locale.
/// Exposed so tests can exercise missing/orphan/mismatch detection on
/// synthetic catalogs without mutating the real ones.
({
  List<String> missingInLocale,
  List<String> unusedKeys,
  List<String> placeholderMismatches,
})
validateCatalogPair(
  Map<String, String> english,
  Map<String, String> locale,
) {
  final englishKeys = english.keys.toSet();
  List<String> placeholders(String value) =>
      RegExp(r'\{(\w+)\}')
          .allMatches(value)
          .map((m) => m.group(1)!)
          .toList()
        ..sort();
  final missingInLocale = <String>[];
  final unusedKeys = <String>[];
  final placeholderMismatches = <String>[];
  locale.forEach((key, value) {
    if (!englishKeys.contains(key)) unusedKeys.add(key);
  });
  english.forEach((key, value) {
    final translated = locale[key];
    if (translated == null) {
      missingInLocale.add(key);
    } else if (placeholders(value).join('\u0000') !=
        placeholders(translated).join('\u0000')) {
      placeholderMismatches.add(key);
    }
  });
  return (
    missingInLocale: missingInLocale,
    unusedKeys: unusedKeys,
    placeholderMismatches: placeholderMismatches,
  );
}
