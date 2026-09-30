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

The remaining migration inventory is intentionally explicit:

- brand-specific camera instructions and template names in
  `frontend/src/lib/camera-brands.ts` are source data and need a data-level
  locale strategy rather than ad-hoc component translation;
- the mobile app has a separate catalog architecture and is tracked separately;
- protocol/configuration values such as `GET`, `POST`, environment variable
  names, HTML/JSON examples, camera/rule identifiers, and the `Nurby` brand are
  intentionally not translated.

The catalog test checks missing keys,
interpolation mismatches, and locale-only extra keys (`locale:key`), so a
contributor pack cannot silently drift from the English source catalog.

Locale is presentation-only. It does not change camera scope, permissions,
retention, rule semantics, timestamps’ source timezone, or model behavior.
