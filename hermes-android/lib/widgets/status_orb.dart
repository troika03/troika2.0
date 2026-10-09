import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../theme/troika_theme.dart';

/// Визуальные состояния главного voice orb из плана Troika 1.0.
enum VoiceOrbState {
  idle,
  listening,
  thinking,
  acting,
  approval,
  speaking,
  done,
  error,
}

/// Единственная центральная анимация главного экрана.
class StatusOrb extends StatefulWidget {
  final VoiceOrbState state;
  final double size;

  const StatusOrb({
    super.key,
    required this.state,
    this.size = 230,
  });

  @override
  State<StatusOrb> createState() => _StatusOrbState();
}

class _StatusOrbState extends State<StatusOrb> with TickerProviderStateMixin {
  late final AnimationController _breath;
  late final AnimationController _motion;

  @override
  void initState() {
    super.initState();
    _breath = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 2600),
    );
    _motion = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 8),
    );
    _applyState();
  }

  @override
  void didUpdateWidget(StatusOrb oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.state != widget.state) _applyState();
  }

  void _applyState() {
    final breathDuration = switch (widget.state) {
      VoiceOrbState.listening => const Duration(milliseconds: 760),
      VoiceOrbState.speaking => const Duration(milliseconds: 620),
      VoiceOrbState.acting => const Duration(milliseconds: 1050),
      VoiceOrbState.thinking => const Duration(milliseconds: 1450),
      _ => const Duration(milliseconds: 2600),
    };
    final motionDuration = switch (widget.state) {
      VoiceOrbState.thinking => const Duration(milliseconds: 1800),
      VoiceOrbState.acting => const Duration(milliseconds: 2200),
      VoiceOrbState.listening ||
      VoiceOrbState.speaking =>
        const Duration(milliseconds: 1200),
      _ => const Duration(seconds: 8),
    };
    _breath
      ..stop()
      ..duration = breathDuration
      ..repeat(reverse: true);
    _motion
      ..stop()
      ..duration = motionDuration
      ..repeat();
  }

  @override
  void dispose() {
    _breath.dispose();
    _motion.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final color = _orbColor(context, widget.state);
    final size = widget.size;
    return Semantics(
      container: true,
      label: 'Состояние голосового ассистента',
      value: widget.state.name,
      child: SizedBox(
        width: size,
        height: size,
        child: AnimatedBuilder(
          animation: Listenable.merge([_breath, _motion]),
          builder: (context, _) {
            final breath = Curves.easeInOut.transform(_breath.value);
            final phase = _motion.value * 2 * math.pi;
            final scale = 0.93 + breath * 0.08;
            return Stack(
              alignment: Alignment.center,
              children: [
                Container(
                  width: size * 0.72,
                  height: size * 0.72,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    boxShadow: [
                      BoxShadow(
                        color: color.withValues(alpha: 0.18 + breath * 0.14),
                        blurRadius: 64,
                        spreadRadius: 8,
                      ),
                    ],
                  ),
                ),
                CustomPaint(
                  size: Size.square(size),
                  painter: _OrbContourPainter(
                    state: widget.state,
                    color: color,
                    phase: phase,
                    breath: breath,
                    radius: size * 0.34 * scale,
                  ),
                ),
                Transform.scale(
                  scale: scale,
                  child: Container(
                    width: size * 0.5,
                    height: size * 0.5,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      gradient: RadialGradient(
                        colors: [
                          color.withValues(alpha: 0.96),
                          color.withValues(alpha: 0.54),
                          color.withValues(alpha: 0),
                        ],
                        stops: const [0, 0.56, 1],
                      ),
                    ),
                  ),
                ),
                AnimatedSwitcher(
                  duration: const Duration(milliseconds: 220),
                  child: _CenterSignal(
                    key: ValueKey(widget.state),
                    state: widget.state,
                    phase: phase,
                    size: size,
                  ),
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}

class _CenterSignal extends StatelessWidget {
  final VoiceOrbState state;
  final double phase;
  final double size;

  const _CenterSignal({
    super.key,
    required this.state,
    required this.phase,
    required this.size,
  });

  @override
  Widget build(BuildContext context) {
    if (state == VoiceOrbState.listening || state == VoiceOrbState.speaking) {
      return Row(
        mainAxisSize: MainAxisSize.min,
        children: List.generate(5, (index) {
          final wave = (math.sin(phase * 2 + index * 0.9) + 1) / 2;
          return Container(
            width: 4,
            height: 12 + wave * 28,
            margin: const EdgeInsets.symmetric(horizontal: 2),
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.9),
              borderRadius: BorderRadius.circular(4),
            ),
          );
        }),
      );
    }

    if (state == VoiceOrbState.thinking) {
      return SizedBox(
        width: size * 0.18,
        height: size * 0.18,
        child: const CircularProgressIndicator(
          strokeWidth: 2.5,
          color: Colors.white,
        ),
      );
    }

    final icon = switch (state) {
      VoiceOrbState.idle => Icons.mic_none_rounded,
      VoiceOrbState.acting => Icons.bolt_outlined,
      VoiceOrbState.approval => Icons.shield_outlined,
      VoiceOrbState.done => Icons.check_rounded,
      VoiceOrbState.error => Icons.priority_high_rounded,
      _ => Icons.circle,
    };
    return Icon(icon, color: Colors.white, size: size * 0.2);
  }
}

class _OrbContourPainter extends CustomPainter {
  final VoiceOrbState state;
  final Color color;
  final double phase;
  final double breath;
  final double radius;

  _OrbContourPainter({
    required this.state,
    required this.color,
    required this.phase,
    required this.breath,
    required this.radius,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final amplitude = switch (state) {
      VoiceOrbState.listening => 8.0,
      VoiceOrbState.speaking => 10.0,
      VoiceOrbState.acting => 5.0,
      VoiceOrbState.thinking => 3.0,
      _ => 2.0 + breath * 2,
    };
    final paint = Paint()
      ..color = color.withValues(alpha: 0.62)
      ..style = PaintingStyle.stroke
      ..strokeWidth = state == VoiceOrbState.done ? 2.2 : 1.5;
    final path = Path();
    const steps = 96;
    for (var index = 0; index <= steps; index++) {
      final angle = index / steps * 2 * math.pi;
      final value = radius +
          math.sin(angle * 3 + phase) * amplitude +
          math.cos(angle * 2 - phase * 0.7) * amplitude * 0.45;
      final point =
          center + Offset(math.cos(angle) * value, math.sin(angle) * value);
      if (index == 0) {
        path.moveTo(point.dx, point.dy);
      } else {
        path.lineTo(point.dx, point.dy);
      }
    }
    path.close();
    canvas.drawPath(path, paint);

    if (state == VoiceOrbState.thinking || state == VoiceOrbState.acting) {
      final arcPaint = Paint()
        ..color = color.withValues(alpha: 0.85)
        ..style = PaintingStyle.stroke
        ..strokeCap = StrokeCap.round
        ..strokeWidth = 3;
      canvas.drawArc(
        Rect.fromCircle(center: center, radius: radius + 14),
        phase,
        math.pi * 0.72,
        false,
        arcPaint,
      );
    }
  }

  @override
  bool shouldRepaint(_OrbContourPainter oldDelegate) {
    return oldDelegate.state != state ||
        oldDelegate.color != color ||
        oldDelegate.phase != phase ||
        oldDelegate.breath != breath ||
        oldDelegate.radius != radius;
  }
}

Color _orbColor(BuildContext context, VoiceOrbState state) {
  return switch (state) {
    VoiceOrbState.error => TroikaColors.error,
    VoiceOrbState.approval => Theme.of(context).colorScheme.primary,
    VoiceOrbState.done => Theme.of(context).colorScheme.primary,
    VoiceOrbState.listening ||
    VoiceOrbState.speaking =>
      Theme.of(context).colorScheme.primary,
    _ => Theme.of(context).colorScheme.primary,
  };
}
