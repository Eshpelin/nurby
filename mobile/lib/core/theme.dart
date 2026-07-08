import 'package:flutter/material.dart';

/// Nurby design language: dark-first, near-black surfaces, single green accent.
/// Mirrors frontend/src/app/globals.css tokens.
abstract final class NurbyColors {
  static const background = Color(0xFF0A0A0A); // 0 0% 3.9%
  static const card = Color(0xFF0E0E0E); // 0 0% 5.5%
  static const cardElevated = Color(0xFF141414); // 0 0% 8%
  static const border = Color(0xFF262626); // 0 0% 14.9%
  static const borderSubtle = Color(0xFF1C1C1C); // 0 0% 11%
  static const foreground = Color(0xFFFAFAFA); // 0 0% 98%
  static const mutedForeground = Color(0xFFA3A3A3); // 0 0% 63.9%
  static const accent = Color(0xFF20C05C); // hsl(142 71% 45%)
  static const danger = Color(0xFFDC2626); // hsl(0 72% 51%)
  static const warning = Color(0xFFF59E0B); // hsl(38 92% 50%)
}

ThemeData buildNurbyTheme() {
  const scheme = ColorScheme.dark(
    surface: NurbyColors.background,
    surfaceContainer: NurbyColors.card,
    surfaceContainerHigh: NurbyColors.cardElevated,
    primary: NurbyColors.accent,
    onPrimary: Colors.black,
    secondary: NurbyColors.accent,
    onSecondary: Colors.black,
    error: NurbyColors.danger,
    onSurface: NurbyColors.foreground,
    outline: NurbyColors.border,
    outlineVariant: NurbyColors.borderSubtle,
  );

  final base = ThemeData(useMaterial3: true, colorScheme: scheme);
  return base.copyWith(
    scaffoldBackgroundColor: NurbyColors.background,
    appBarTheme: const AppBarTheme(
      backgroundColor: NurbyColors.background,
      foregroundColor: NurbyColors.foreground,
      elevation: 0,
      centerTitle: false,
      titleTextStyle: TextStyle(
        color: NurbyColors.foreground,
        fontSize: 18,
        fontWeight: FontWeight.w600,
      ),
    ),
    cardTheme: CardTheme(
      color: NurbyColors.card,
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: const BorderSide(color: NurbyColors.border),
      ),
      margin: EdgeInsets.zero,
    ),
    dividerTheme: const DividerThemeData(color: NurbyColors.border, thickness: 1),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: NurbyColors.card,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: NurbyColors.border),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: NurbyColors.border),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(10),
        borderSide: const BorderSide(color: NurbyColors.accent),
      ),
      hintStyle: const TextStyle(color: NurbyColors.mutedForeground),
      labelStyle: const TextStyle(color: NurbyColors.mutedForeground),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: NurbyColors.accent,
        foregroundColor: Colors.black,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
        textStyle: const TextStyle(fontWeight: FontWeight.w600, fontSize: 15),
      ),
    ),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: NurbyColors.card,
      indicatorColor: NurbyColors.accent.withValues(alpha: 0.15),
      surfaceTintColor: Colors.transparent,
      labelTextStyle: WidgetStateProperty.resolveWith((states) => TextStyle(
            fontSize: 11,
            fontWeight: FontWeight.w500,
            color: states.contains(WidgetState.selected)
                ? NurbyColors.accent
                : NurbyColors.mutedForeground,
          )),
      iconTheme: WidgetStateProperty.resolveWith((states) => IconThemeData(
            color: states.contains(WidgetState.selected)
                ? NurbyColors.accent
                : NurbyColors.mutedForeground,
          )),
    ),
    snackBarTheme: const SnackBarThemeData(
      backgroundColor: NurbyColors.cardElevated,
      contentTextStyle: TextStyle(color: NurbyColors.foreground),
      behavior: SnackBarBehavior.floating,
    ),
    chipTheme: base.chipTheme.copyWith(
      backgroundColor: NurbyColors.card,
      side: const BorderSide(color: NurbyColors.border),
      labelStyle: const TextStyle(color: NurbyColors.foreground, fontSize: 13),
    ),
  );
}

/// Mono style for timestamps and identifiers (Geist Mono equivalent).
const monoStyle = TextStyle(
  fontFamily: 'Menlo',
  fontFamilyFallback: ['Roboto Mono', 'monospace'],
  fontSize: 12,
  color: NurbyColors.mutedForeground,
);
