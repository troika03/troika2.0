import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

/// Original brand artwork and the SVG shapes exported by the approved Figma file.
class TroikaBrand extends StatelessWidget {
  const TroikaBrand({super.key});

  @override
  Widget build(BuildContext context) => SvgPicture.asset(
        Theme.of(context).brightness == Brightness.dark
            ? 'assets/brand/logo-ru-reverse.svg'
            : 'assets/brand/logo-ru-primary.svg',
        width: 124,
        height: 32,
        semanticsLabel: 'Тройка',
      );
}

class TroikaSvgIcon extends StatelessWidget {
  final String name;
  final Color? color;
  final double size;
  const TroikaSvgIcon(this.name, {super.key, this.color, this.size = 16});

  @override
  Widget build(BuildContext context) => SvgPicture.asset(
        'assets/brand/$name.svg',
        width: size,
        height: size,
        excludeFromSemantics: true,
        colorFilter: ColorFilter.mode(
          color ??
              IconTheme.of(context).color ??
              Theme.of(context).colorScheme.onSurface,
          BlendMode.srcIn,
        ),
      );
}
