import 'package:flutter_test/flutter_test.dart';
import 'package:nurby_mobile/core/i18n.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('catalogs have no missing keys or interpolation mismatches', () {
    final result = validateMobileCatalogs();
    expect(result.missingInLocale, isEmpty);
    expect(result.placeholderMismatches, isEmpty);
    expect(result.unusedKeys, isEmpty);
  });

  test('falls back to English and preserves an unresolved key visibly', () {
    expect(
      translateLocale(AppLocale.es, 'settings.language'),
      'Idioma',
    );
    // A key missing from every catalog renders the key itself, never an
    // empty control.
    expect(
      translateLocale(AppLocale.es, 'settings.not_yet_translated'),
      'settings.not_yet_translated',
    );
  });

  test('detects drift in a contributor locale', () {
    final result = validateCatalogPair({
      'a.present': 'Present',
      'a.count': '{count} items',
    }, {
      'a.present': 'Presente',
      'a.orphan': 'Solo aquí',
      'a.count': '{n} elementos',
    });
    expect(result.missingInLocale, isEmpty);
    expect(result.unusedKeys, ['a.orphan']);
    expect(result.placeholderMismatches, ['a.count']);
  });

  test('keeps interpolation stable across locales', () {
    expect(
      translateLocale(AppLocale.es, 'push.camera_prefix', {'camera': 'Puerta'}),
      'Cámara: Puerta',
    );
    expect(
      translateLocale(AppLocale.en, 'push.camera_prefix'),
      'Camera: {camera}',
    );
  });

  test('explicit choice wins, then device language, then English', () {
    expect(effectiveLocale(AppLocale.es), AppLocale.es);
    // The binding's platform dispatcher reports en-US under the test env.
    expect(effectiveLocale(null), AppLocale.en);
    expect(AppLocale.fromLanguageCode('fr'), isNull);
    expect(AppLocale.fromLanguageCode('es'), AppLocale.es);
    expect(AppLocale.fromLanguageCode(null), isNull);
  });
}
