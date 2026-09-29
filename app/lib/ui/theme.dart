import 'package:flutter/material.dart';

const spartaRed = Color(0xFFC8102E);
const spartaGold = Color(0xFFE7B62C);

ThemeData buildTheme(Brightness brightness) {
  final dark = brightness == Brightness.dark;
  var scheme = ColorScheme.fromSeed(seedColor: spartaRed, brightness: brightness);
  scheme = scheme.copyWith(
    primary: dark ? const Color(0xFFFF4D5E) : spartaRed,
    onPrimary: Colors.white,
    secondary: spartaGold,
    onSecondary: const Color(0xFF231A00),
    surface: dark ? const Color(0xFF140D0D) : const Color(0xFFFFF8F7),
    surfaceContainerLowest: dark ? const Color(0xFF0E0909) : Colors.white,
    surfaceContainerLow: dark ? const Color(0xFF1A1111) : const Color(0xFFFCEFEE),
    surfaceContainer: dark ? const Color(0xFF1F1414) : const Color(0xFFF7E7E5),
    surfaceContainerHigh: dark ? const Color(0xFF281A1A) : const Color(0xFFF1DEDC),
    surfaceContainerHighest: dark ? const Color(0xFF322121) : const Color(0xFFEBD5D3),
  );
  final base = ThemeData(colorScheme: scheme, useMaterial3: true, brightness: brightness, fontFamily: 'Inter');
  return base.copyWith(
    scaffoldBackgroundColor: scheme.surface,
    cardTheme: CardThemeData(
      color: scheme.surfaceContainerLow,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: BorderSide(color: scheme.outlineVariant.withValues(alpha: 0.5)),
      ),
    ),
    inputDecorationTheme: const InputDecorationTheme(border: OutlineInputBorder(), isDense: true),
    navigationRailTheme: NavigationRailThemeData(
      backgroundColor: scheme.surfaceContainerLowest,
      indicatorColor: scheme.primary.withValues(alpha: 0.18),
      selectedIconTheme: IconThemeData(color: scheme.primary),
      selectedLabelTextStyle: TextStyle(color: scheme.primary, fontWeight: FontWeight.w600),
    ),
    snackBarTheme: const SnackBarThemeData(behavior: SnackBarBehavior.floating, width: 560),
    visualDensity: VisualDensity.standard,
  );
}
