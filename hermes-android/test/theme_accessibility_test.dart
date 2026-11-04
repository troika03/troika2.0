import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:troika_assistant/config/troika_config.dart';
import 'package:troika_assistant/theme/troika_theme.dart';
import 'package:troika_assistant/widgets/troika_page.dart';

double contrast(Color first, Color second) {
  final a = first.computeLuminance();
  final b = second.computeLuminance();
  return a > b ? (a + 0.05) / (b + 0.05) : (b + 0.05) / (a + 0.05);
}

void main() {
  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    await TroikaConfig.init();
  });

  test(
    'controls retain readable text with every saved accent and theme',
    () async {
      for (final accent in [
        'mint',
        'amber',
        'teal',
        'blue',
        'violet',
        'rose',
        'green',
      ]) {
        await TroikaConfig.setInterfaceAccent(accent);
        for (final dark in [true, false]) {
          final base = dark ? buildTroikaTheme() : buildTroikaLightTheme();
          for (final theme in [base, troikaPageTheme(base)]) {
            final scheme = theme.colorScheme;
            expect(
              contrast(scheme.onPrimary, scheme.primary),
              greaterThanOrEqualTo(4.5),
              reason: '$accent / $dark primary',
            );
            expect(
              contrast(scheme.onSurface, scheme.surface),
              greaterThanOrEqualTo(4.5),
              reason: '$accent / $dark surface',
            );
            expect(
              contrast(scheme.error, theme.scaffoldBackgroundColor),
              greaterThanOrEqualTo(4.5),
              reason: '$accent / $dark error',
            );
          }
        }
      }
    },
  );

  for (final dark in [true, false]) {
    testWidgets(
      'form remains usable with large text in ${dark ? 'dark' : 'light'}',
      (tester) async {
        tester.view.physicalSize = const Size(360, 800);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        var saved = false;
        final formKey = GlobalKey<FormState>();
        await tester.pumpWidget(
          MaterialApp(
            theme: troikaPageTheme(
              dark ? buildTroikaTheme() : buildTroikaLightTheme(),
            ),
            builder: (context, child) => MediaQuery(
              data: MediaQuery.of(
                context,
              ).copyWith(textScaler: const TextScaler.linear(2)),
              child: child!,
            ),
            home: Scaffold(
              body: SingleChildScrollView(
                padding: const EdgeInsets.all(20),
                child: Form(
                  key: formKey,
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      TextFormField(
                        decoration: const InputDecoration(
                          labelText: 'Название',
                        ),
                        validator: (value) =>
                            value == null || value.trim().isEmpty
                            ? 'Введите название'
                            : null,
                      ),
                      const SizedBox(height: 24),
                      FilledButton(
                        onPressed: () =>
                            saved = formKey.currentState!.validate(),
                        child: const Text('Сохранить'),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        );
        final saveButton = find.widgetWithText(FilledButton, 'Сохранить');
        expect(tester.getSize(saveButton).height, greaterThanOrEqualTo(48));
        await tester.tap(saveButton);
        await tester.pumpAndSettle();
        expect(find.text('Введите название'), findsOneWidget);
        expect(saved, isFalse);
        await tester.enterText(find.byType(TextFormField), 'Моё дело');
        await tester.tap(saveButton);
        await tester.pumpAndSettle();
        expect(saved, isTrue);
        expect(tester.takeException(), isNull);
      },
    );
  }
}
