import 'dart:math' as math;
import 'package:flutter/material.dart';
import '../services/assistant_service.dart';
import '../theme/troika_theme.dart';

/// Мягкий «дышащий» орб Тройки.
///
/// Без вращающихся пунктирных колец и неона — спокойное радиальное свечение,
/// которое дышит (масштаб + яркость) и слегка «оживает» в активных состояниях.
/// Один фирменный цвет, чистая форма.
class StatusOrb extends StatefulWidget {
  final AssistantState state;

  const StatusOrb({super.key, required this.state});

  @override
  State<StatusOrb> createState() => _StatusOrbState();
}

class _StatusOrbState extends State<StatusOrb>
    with TickerProviderStateMixin {
  late final AnimationController _breath; // медленное дыхание ядра
  late final AnimationController _wave;   // лёгкая «жидкая» волна по контуру

  @override
  void initState() {
    super.initState();
    _breath = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 2600),
    )..repeat(reverse: true);
    _wave = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 8),
    )..repeat();
    _applyState();
  }

  @override
  void didUpdateWidget(StatusOrb oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.state != widget.state) _applyState();
  }

  void _applyState() {
    final active = widget.state == AssistantState.recording ||
        widget.state == AssistantState.wakeDetected;
    final thinking = widget.state == AssistantState.processing;
    _breath.duration = Duration(
      milliseconds: active ? 1100 : (thinking ? 1700 : 2600),
    );
    if (!_breath.isAnimating) _breath.repeat(reverse: true);
    _wave.duration = Duration(seconds: active ? 4 : 8);
    if (!_wave.isAnimating) _wave.repeat();
  }

  @override
  void dispose() {
    _breath.dispose();
    _wave.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final color = TroikaColors.forState(widget.state);
    const size = 230.0;

    return SizedBox(
      width: size,
      height: size,
      child: AnimatedBuilder(
        animation: Listenable.merge([_breath, _wave]),
        builder: (context, _) {
          final b = Curves.easeInOut.transform(_breath.value); // 0..1
          final scale = 0.92 + b * 0.10;
          return Stack(
            alignment: Alignment.center,
            children: [
              // Большое мягкое свечение
              Container(
                width: size * 0.78,
                height: size * 0.78,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  boxShadow: [
                    BoxShadow(
                      color: color.withOpacity(0.18 + b * 0.16),
                      blurRadius: 70,
                      spreadRadius: 10,
                    ),
                  ],
                ),
              ),

              // Жидкий контур (тонкая волнистая граница)
              CustomPaint(
                size: const Size(size, size),
                painter: _BlobPainter(
                  color: color,
                  phase: _wave.value * 2 * math.pi,
                  amplitude: 3.0 + b * 4.0,
                  radius: size * 0.34 * scale,
                  opacity: 0.5,
                ),
              ),

              // Ядро — мягкий радиальный градиент
              Transform.scale(
                scale: scale,
                child: Container(
                  width: size * 0.5,
                  height: size * 0.5,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    gradient: RadialGradient(
                      colors: [
                        color.withOpacity(0.95),
                        color.withOpacity(0.55),
                        color.withOpacity(0.0),
                      ],
                      stops: const [0.0, 0.55, 1.0],
                    ),
                  ),
                ),
              ),

              // Маленькая яркая сердцевина
              Container(
                width: size * 0.16,
                height: size * 0.16,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: Colors.white.withOpacity(0.92),
                  boxShadow: [
                    BoxShadow(color: color, blurRadius: 24, spreadRadius: 2),
                  ],
                ),
              ),
            ],
          );
        },
      ),
    );
  }
}

/// Рисует мягкую «жидкую» окружность — лёгкое синусоидальное искажение радиуса.
class _BlobPainter extends CustomPainter {
  final Color color;
  final double phase;
  final double amplitude;
  final double radius;
  final double opacity;

  _BlobPainter({
    required this.color,
    required this.phase,
    required this.amplitude,
    required this.radius,
    required this.opacity,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final paint = Paint()
      ..color = color.withOpacity(opacity)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.4;

    final path = Path();
    const steps = 90;
    for (int i = 0; i <= steps; i++) {
      final t = (i / steps) * 2 * math.pi;
      // две гармоники дают мягкое «живое» колыхание
      final r = radius +
          math.sin(t * 3 + phase) * amplitude +
          math.cos(t * 2 - phase * 0.7) * amplitude * 0.5;
      final p = center + Offset(math.cos(t) * r, math.sin(t) * r);
      if (i == 0) {
        path.moveTo(p.dx, p.dy);
      } else {
        path.lineTo(p.dx, p.dy);
      }
    }
    path.close();
    canvas.drawPath(path, paint);
  }

  @override
  bool shouldRepaint(_BlobPainter old) =>
      old.phase != phase ||
      old.amplitude != amplitude ||
      old.radius != radius ||
      old.color != color;
}
