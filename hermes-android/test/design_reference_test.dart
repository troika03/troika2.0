import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:troika_assistant/config/troika_config.dart';
import 'package:troika_assistant/screens/home_screen.dart';
import 'package:troika_assistant/services/assistant_service.dart';
import 'package:troika_assistant/theme/troika_theme.dart';
import 'package:troika_assistant/widgets/troika_brand.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    final messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    // Render the real home without opening a microphone or an audio device.
    for (final channel in [
      'com.llfbandit.record/messages',
      'flutter_tts',
      'xyz.luan/audioplayers.global',
      'xyz.luan/audioplayers.global/events',
    ]) {
      messenger.setMockMethodCallHandler(
        MethodChannel(channel),
        (_) async => null,
      );
    }
    messenger.setMockMethodCallHandler(
      const MethodChannel('xyz.luan/audioplayers'),
      (call) async {
        if (call.method == 'create') {
          final playerId = (call.arguments as Map)['playerId'];
          messenger.setMockMethodCallHandler(
            MethodChannel('xyz.luan/audioplayers/events/$playerId'),
            (_) async => null,
          );
        }
        return null;
      },
    );
  });

  setUpAll(() async {
    final font = FontLoader('Golos Text')
      ..addFont(rootBundle.load('assets/fonts/GolosText-Variable.ttf'));
    await font.load();
    final icons = FontLoader('MaterialIcons')
      ..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'));
    await icons.load();
  });

  for (final dark in [true, false]) {
    for (final width in [360.0, 390.0, 430.0]) {
      testWidgets('native home ${dark ? 'dark' : 'light'} at $width', (
        tester,
      ) async {
        debugDisableShadows = false;
        SharedPreferences.setMockInitialValues({
          'troika_server_url': 'https://example.invalid',
        });
        await TroikaConfig.init();
        tester.view.physicalSize = Size(width, 844);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final assistant = AssistantService();
        final boundary = GlobalKey();
        await tester.pumpWidget(
          ChangeNotifierProvider<AssistantService>.value(
            value: assistant,
            child: MaterialApp(
              theme: dark ? buildTroikaTheme() : buildTroikaLightTheme(),
              builder: (context, child) => MediaQuery(
                data: MediaQuery.of(context).copyWith(
                  disableAnimations: true,
                  textScaler: TextScaler.linear(width == 360 ? 1.5 : 1),
                ),
                child: RepaintBoundary(key: boundary, child: child!),
              ),
              home: const HomeScreen(windowsShellOverride: false),
            ),
          ),
        );
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        expect(find.byType(TroikaBrand), findsOneWidget);
        expect(find.text('Чем помочь?'), findsOneWidget);
        final text = tester.widget<Text>(find.text('Чем помочь?'));
        final context = tester.element(find.text('Чем помочь?'));
        expect(
          text.style?.fontFamily ??
              Theme.of(context).textTheme.displaySmall?.fontFamily,
          'Golos Text',
        );
        final talk = find.byTooltip('Текст');
        expect(tester.getRect(talk).right, lessThanOrEqualTo(width));
        expect(
          tester.getRect(find.text('Дела')).right,
          lessThanOrEqualTo(width),
        );
        final render =
            boundary.currentContext!.findRenderObject()!
                as RenderRepaintBoundary;
        await tester.runAsync(() async {
          final image = await render.toImage();
          final png = await image.toByteData(format: ui.ImageByteFormat.png);
          if (Platform.environment['TROIKA_DESIGN_RENDERS']
              case final String folder) {
            await Directory(folder).create(recursive: true);
            await File(
              '$folder/android-${dark ? 'dark' : 'light'}-${width.toInt()}.png',
            ).writeAsBytes(png!.buffer.asUint8List());
          }
          image.dispose();
        });
        await tester.pumpWidget(const SizedBox.shrink());
        assistant.dispose();
        await tester.pumpAndSettle();
        debugDisableShadows = true;
      });
    }
  }
}
