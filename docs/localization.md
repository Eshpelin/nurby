# Web localization

Nurby’s web catalog lives in `frontend/src/lib/i18n.ts`. English is the source
catalog, and every supported locale must contain the same keys and the same
`{named}` interpolation placeholders. `translate()` falls back to English and
then to the key itself, so a missing translation is visible to maintainers
instead of rendering an empty control.

Run the catalog contract and frontend suite with:

```sh
npm test --prefix frontend -- --run src/lib/__tests__/i18n.test.ts
```

To add a language, extend the `Locale` union, add its catalog entries and
`supportedLocales` label, then run the test. Keep labels and accessibility
copy in the catalog when a surface is migrated; do not translate camera IDs,
rule keys, API values, or security decisions.

The first proof currently covers the Settings language selector. The migrated
web surfaces now include shell/navigation, onboarding, alert/event pages,
reports, camera activity/package evidence, camera voice settings, camera setup
helpers, Smart Track settings, Settings tuning/digest copy, AI usage reporting,
rule editors and execution logs, widget setup, and identity review surfaces.

# Mobile localization

The mobile app has its own catalog in `mobile/lib/core/i18n.dart`, mirroring
the web one: flat typed keys, `{named}` interpolation, English fallback chain
(locale → English → the key itself), and a contract test
(`mobile/test/i18n_test.dart`) checking missing keys, placeholder parity, and
orphan contributor keys. `AppLocale` is the locale union; adding a language
means an enum entry, a catalog, and test coverage. Run:

```sh
flutter test --prefix mobile  # from the repository root, or:
cd mobile && flutter test test/i18n_test.dart
```

The choice lives in Settings → Language, persists on the device, syncs to the
account via `PATCH /api/auth/me/locale`, and is adopted from the account on
login when the device has no explicit choice. Migrated mobile surfaces:
shell/navigation, offline banner, push-notification copy, server
address/login/setup/QR pairing, settings hub and the language picker, home,
and the activity filter chips. Framework chrome (text-selection menus,
system tooltips) localizes through `flutter_localizations`.

The remaining migration inventory is intentionally explicit:

- brand-specific camera instructions in `frontend/src/lib/camera-brands.ts`
  now use a data-level locale strategy: steps, notes, and template labels
  carry `LocalizedText {en, es}` inline with English fallback, and
  `validateCameraBrands()` enforces full-or-no Spanish coverage per field
  (see `frontend/src/lib/__tests__/camera-brands.test.ts`). Menu paths, tool
  names, and URL fragments stay as written because the camera’s own UI and
  the wire format are English regardless of app locale;
- the mobile app’s remaining feature screens (embedded activity lists,
  cameras, people, rules, review, guardian, voice, search, and the settings
  detail sections) still hold literal English copy and are tracked in
  `docs/i18n-inline-copy-audit.md`;
- protocol/configuration values such as `GET`, `POST`, environment variable
  names, HTML/JSON examples, camera/rule identifiers, and the `Nurby` brand
  are intentionally not translated.

The catalog tests check missing keys, interpolation mismatches, and
locale-only extra keys (`locale:key`), so a contributor pack cannot silently
drift from the English source catalog.

Locale is presentation-only. It does not change camera scope, permissions,
retention, rule semantics, timestamps’ source timezone, or model behavior.
