import 'package:flutter/material.dart';
import '../config/troika_config.dart';
import '../theme/troika_theme.dart';

/// Shared palette for the voice home and secondary screens.
class TroikaPalette {
  final bool dark;
  const TroikaPalette(this.dark);
  factory TroikaPalette.of(BuildContext context) =>
      TroikaPalette(Theme.of(context).brightness == Brightness.dark);

  Color get bg => dark ? TroikaColors.bg : TroikaLightColors.bg;
  Color get surface => dark ? TroikaColors.surface : TroikaLightColors.surface;
  Color get surfaceHi =>
      dark ? TroikaColors.surfaceHi : TroikaLightColors.surfaceHi;
  Color get text => dark ? TroikaColors.text : TroikaLightColors.text;
  Color get textMuted =>
      dark ? TroikaColors.textMuted : TroikaLightColors.textMuted;
  Color get textFaint => textMuted;
  Color get line => dark ? const Color(0xFF36362E) : const Color(0xFFDEDBD1);
  Color get accent =>
      TroikaColors.accentFor(TroikaConfig.interfaceAccent, dark: dark);
  Color get tint => accent.withValues(alpha: dark ? 0.16 : 0.11);
}

/// Shared solid surface from the approved light and dark designs.
class TroikaGlass extends StatelessWidget {
  final Widget child;
  final double radius;
  const TroikaGlass({super.key, required this.child, this.radius = 20});

  @override
  Widget build(BuildContext context) {
    final p = TroikaPalette.of(context);
    final content = DecoratedBox(
      decoration: BoxDecoration(
        color: p.surface,
        borderRadius: BorderRadius.circular(radius),
        border: Border.all(color: p.line),
      ),
      child: child,
    );
    return ClipRRect(
      borderRadius: BorderRadius.circular(radius),
      child: content,
    );
  }
}

ThemeData troikaPageTheme(ThemeData base) {
  final p = TroikaPalette(base.brightness == Brightness.dark);
  final shape = RoundedRectangleBorder(borderRadius: BorderRadius.circular(20));
  final border = OutlineInputBorder(
      borderRadius: BorderRadius.circular(16),
      borderSide: BorderSide(color: p.line));
  return base.copyWith(
    scaffoldBackgroundColor: p.bg,
    colorScheme: base.colorScheme.copyWith(
        primary: p.accent,
        onPrimary: p.dark ? const Color(0xFF2C1B06) : Colors.white,
        surface: p.surface,
        onSurface: p.text,
        onSurfaceVariant: p.textMuted,
        outline: p.line,
        outlineVariant: p.line,
        primaryContainer: p.tint,
        onPrimaryContainer: p.accent),
    textTheme: base.textTheme.apply(bodyColor: p.text, displayColor: p.text),
    appBarTheme: AppBarTheme(
        backgroundColor: p.bg,
        foregroundColor: p.text,
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: false,
        titleTextStyle: TextStyle(
            color: p.text, fontSize: 20, fontWeight: FontWeight.w600)),
    cardTheme: CardThemeData(
        color: p.surface,
        elevation: 0,
        margin: const EdgeInsets.only(bottom: 12),
        shape: shape),
    listTileTheme: ListTileThemeData(
        textColor: p.text,
        iconColor: p.accent,
        minVerticalPadding: 12,
        contentPadding: const EdgeInsets.symmetric(horizontal: 16),
        titleTextStyle:
            TextStyle(color: p.text, fontSize: 16, fontWeight: FontWeight.w600),
        subtitleTextStyle:
            TextStyle(color: p.textMuted, fontSize: 14, height: 1.4)),
    inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: p.surface,
        border: border,
        enabledBorder: border,
        focusedBorder:
            border.copyWith(borderSide: BorderSide(color: p.accent, width: 2)),
        contentPadding: const EdgeInsets.all(16),
        hintStyle: TextStyle(color: p.textMuted),
        labelStyle: TextStyle(color: p.textMuted)),
    filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
            minimumSize: const Size(48, 52),
            shape:
                RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
            textStyle:
                const TextStyle(fontSize: 16, fontWeight: FontWeight.w600))),
    outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
            minimumSize: const Size(48, 48),
            side: BorderSide(color: p.line),
            shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(16)))),
    iconButtonTheme: IconButtonThemeData(
        style: IconButton.styleFrom(minimumSize: const Size(48, 48))),
    chipTheme: base.chipTheme.copyWith(
        backgroundColor: p.surface,
        selectedColor: p.tint,
        side: BorderSide(color: p.line),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        labelStyle: TextStyle(color: p.text),
        padding: const EdgeInsets.all(8)),
    dividerTheme: DividerThemeData(color: p.line, space: 24, thickness: 1),
    dialogTheme: DialogThemeData(backgroundColor: p.surface, shape: shape),
    bottomSheetTheme: BottomSheetThemeData(
        backgroundColor: p.surface,
        showDragHandle: true,
        shape: const RoundedRectangleBorder(
            borderRadius: BorderRadius.vertical(top: Radius.circular(28)))),
    popupMenuTheme: PopupMenuThemeData(color: p.surface, shape: shape),
  );
}

/// A shared, responsive shell for every secondary route.
class TroikaPage extends StatelessWidget {
  final PreferredSizeWidget? appBar;
  final Widget? body, floatingActionButton, bottomNavigationBar;
  final Color? backgroundColor;
  final bool? resizeToAvoidBottomInset;
  const TroikaPage(
      {super.key,
      this.appBar,
      this.body,
      this.floatingActionButton,
      this.bottomNavigationBar,
      this.backgroundColor,
      this.resizeToAvoidBottomInset});

  @override
  Widget build(BuildContext context) {
    final theme = troikaPageTheme(Theme.of(context));
    return Theme(
        data: theme,
        child: Scaffold(
          backgroundColor: backgroundColor ?? theme.scaffoldBackgroundColor,
          appBar: appBar,
          floatingActionButton: floatingActionButton,
          bottomNavigationBar: bottomNavigationBar,
          resizeToAvoidBottomInset: resizeToAvoidBottomInset,
          body: SafeArea(
              top: appBar == null,
              child: Align(
                  alignment: Alignment.topCenter,
                  child: ConstrainedBox(
                      constraints: const BoxConstraints(maxWidth: 720),
                      child: SizedBox(width: double.infinity, child: body)))),
        ));
  }
}

/// Capture page styling before building a route, including its dialogs.
class TroikaPageScope extends StatelessWidget {
  final Widget child;
  const TroikaPageScope({super.key, required this.child});
  @override
  Widget build(BuildContext context) =>
      Theme(data: troikaPageTheme(Theme.of(context)), child: child);
}

class TroikaIntro extends StatelessWidget {
  final String title, subtitle;
  final IconData icon;
  const TroikaIntro(
      {super.key,
      required this.title,
      required this.subtitle,
      required this.icon});
  @override
  Widget build(BuildContext context) {
    final p = TroikaPalette.of(context);
    return Padding(
        padding: const EdgeInsets.only(top: 8, bottom: 24),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          TroikaIcon(icon: icon, size: 56),
          const SizedBox(height: 20),
          Text(title,
              style: TextStyle(
                  color: p.text,
                  fontSize: 28,
                  height: 1.15,
                  fontWeight: FontWeight.w600,
                  letterSpacing: -0.6)),
          const SizedBox(height: 8),
          Text(subtitle,
              style: TextStyle(color: p.textMuted, fontSize: 16, height: 1.45)),
        ]));
  }
}

class TroikaIcon extends StatelessWidget {
  final IconData icon;
  final double size;
  final Color? color;
  const TroikaIcon({super.key, required this.icon, this.size = 48, this.color});
  @override
  Widget build(BuildContext context) {
    final p = TroikaPalette.of(context);
    final tone = color ?? p.accent;
    return Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
            color: tone.withValues(alpha: p.dark ? 0.13 : 0.09),
            borderRadius: BorderRadius.circular(size / 3)),
        child: Icon(icon, color: tone, size: size * 0.48));
  }
}

class TroikaActionCard extends StatelessWidget {
  final IconData icon;
  final String title, subtitle;
  final VoidCallback onTap;
  final Color? color;
  const TroikaActionCard(
      {super.key,
      required this.icon,
      required this.title,
      required this.subtitle,
      required this.onTap,
      this.color});
  @override
  Widget build(BuildContext context) {
    final p = TroikaPalette.of(context);
    return Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: TroikaGlass(
            child: Material(
                color: Colors.transparent,
                borderRadius: BorderRadius.circular(20),
                clipBehavior: Clip.antiAlias,
                child: InkWell(
                    onTap: onTap,
                    child: Padding(
                        padding: const EdgeInsets.all(20),
                        child: Row(children: [
                          TroikaIcon(icon: icon, color: color),
                          const SizedBox(width: 16),
                          Expanded(
                              child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                Text(title,
                                    style: TextStyle(
                                        color: p.text,
                                        fontSize: 16,
                                        fontWeight: FontWeight.w600)),
                                const SizedBox(height: 4),
                                Text(subtitle,
                                    style: TextStyle(
                                        color: p.textMuted, height: 1.4)),
                              ])),
                          const SizedBox(width: 8),
                          Icon(Icons.arrow_forward_rounded,
                              color: p.textMuted, size: 20),
                        ]))))));
  }
}

class TroikaEmptyState extends StatelessWidget {
  final IconData icon;
  final String title, message;
  final String? actionLabel;
  final VoidCallback? onAction;
  const TroikaEmptyState(
      {super.key,
      required this.icon,
      required this.title,
      required this.message,
      this.actionLabel,
      this.onAction});
  @override
  Widget build(BuildContext context) {
    final p = TroikaPalette.of(context);
    return Padding(
        padding: const EdgeInsets.all(24),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          TroikaIcon(icon: icon, size: 64),
          const SizedBox(height: 24),
          Text(title,
              textAlign: TextAlign.center,
              style: TextStyle(
                  color: p.text, fontSize: 20, fontWeight: FontWeight.w600)),
          const SizedBox(height: 8),
          Text(message,
              textAlign: TextAlign.center,
              style: TextStyle(color: p.textMuted, fontSize: 16, height: 1.45)),
          if (onAction != null) ...[
            const SizedBox(height: 24),
            FilledButton(
                onPressed: onAction, child: Text(actionLabel ?? 'Продолжить'))
          ],
        ]));
  }
}

const troikaAccentChoices = <(String, String)>[
  ('amber', 'Янтарный'),
  ('teal', 'Бирюзовый'),
  ('blue', 'Синий'),
  ('violet', 'Фиолетовый'),
  ('rose', 'Розовый'),
  ('green', 'Зелёный'),
];
