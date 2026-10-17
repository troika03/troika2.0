import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:troika_assistant/widgets/status_orb.dart';

void main() {
  for (final state in [VoiceOrbState.idle, VoiceOrbState.thinking]) {
    for (final reduced in [false, true]) {
      testWidgets('${state.name} respects reduced motion: $reduced',
          (tester) async {
        await tester.pumpWidget(MaterialApp(
          home: MediaQuery(
            data: MediaQueryData(disableAnimations: reduced),
            child: StatusOrb(state: state),
          ),
        ));
        await tester.pump();
        await tester.pump(const Duration(seconds: 1));

        // A static voice state must not keep scheduling animation frames.
        expect(tester.binding.hasScheduledFrame, !reduced);
        if (reduced) await tester.pumpAndSettle();

        await tester.pumpWidget(const SizedBox.shrink());
      });
    }
  }
}
