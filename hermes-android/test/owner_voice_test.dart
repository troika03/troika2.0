import 'dart:async';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:troika_assistant/config/troika_config.dart';
import 'package:troika_assistant/screens/owner_voice_screen.dart';
import 'package:troika_assistant/services/owner_voice_service.dart';
import 'package:troika_assistant/theme/troika_theme.dart';

class _VoiceService extends OwnerVoiceService {
  OwnerVoiceStatus current;
  Completer<OwnerVoiceStatus>? pending;
  int enrollCalls = 0;
  int cancelCalls = 0;
  bool reject = false;

  _VoiceService({this.current = const OwnerVoiceStatus()});

  @override
  Future<OwnerVoiceStatus> status() async => current;

  @override
  Future<OwnerVoiceStatus> enroll() async {
    enrollCalls++;
    if (reject) {
      throw PlatformException(
        code: 'sample_short',
        message: 'Говори не меньше четырёх секунд.',
      );
    }
    if (pending != null) return pending!.future;
    final samples = current.samples + 1;
    return current = OwnerVoiceStatus(samples: samples, enrolled: samples >= 3);
  }

  @override
  Future<OwnerVoiceStatus> setEnabled(bool enabled) async =>
      current = OwnerVoiceStatus(
        enrolled: current.enrolled,
        samples: current.samples,
        enabled: enabled,
      );

  @override
  Future<OwnerVoiceStatus> delete() async => current = const OwnerVoiceStatus();

  @override
  Future<void> cancel() async {
    cancelCalls++;
  }
}

Future<void> _show(
  WidgetTester tester,
  _VoiceService service, {
  Future<bool> Function()? permission,
}) async {
  await tester.pumpWidget(
    MaterialApp(
      theme: buildTroikaTheme(),
      home: OwnerVoiceScreen(
        service: service,
        requestMicrophone: permission ?? () async => true,
      ),
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('com.troika.hermes/owner_voice');

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    await TroikaConfig.init();
  });

  setUpAll(() async {
    final font = FontLoader('Golos Text')
      ..addFont(rootBundle.load('assets/fonts/GolosText-Variable.ttf'));
    await font.load();
    final icons = FontLoader('MaterialIcons')
      ..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'));
    await icons.load();
  });

  test(
    'native bridge forwards enable and rejects unavailable responses',
    () async {
      final calls = <MethodCall>[];
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, (call) async {
            calls.add(call);
            if (call.method == 'delete') return null;
            return {
              'enrolled': true,
              'enabled':
                  call.arguments is Map && call.arguments['enabled'] == true,
              'samples': 3,
            };
          });
      addTearDown(
        () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
            .setMockMethodCallHandler(channel, null),
      );
      final service = OwnerVoiceService();
      expect((await service.setEnabled(true)).enabled, isTrue);
      expect(calls.single.arguments, {'enabled': true});
      await expectLater(service.delete(), throwsA(isA<PlatformException>()));
    },
  );

  testWidgets(
    'three samples precede explicit enable and deletion resets profile',
    (tester) async {
      final service = _VoiceService();
      await _show(tester, service);
      expect(
        tester.widget<SwitchListTile>(find.byType(SwitchListTile)).onChanged,
        isNull,
      );
      for (var sample = 0; sample < 3; sample++) {
        expect(find.text('Фраза ${sample + 1} из 3'), findsOneWidget);
        await tester.ensureVisible(find.text('Записать фразу'));
        await tester.tap(find.text('Записать фразу'));
        await tester.pumpAndSettle();
      }
      expect(service.current.enrolled, isTrue);
      expect(service.current.enabled, isFalse);
      await tester.ensureVisible(find.byType(SwitchListTile));
      await tester.tap(find.byType(SwitchListTile));
      await tester.pumpAndSettle();
      expect(service.current.enabled, isTrue);
      await tester.ensureVisible(find.text('Удалить образец голоса'));
      await tester.tap(find.text('Удалить образец голоса'));
      await tester.pumpAndSettle();
      expect(service.current.enrolled, isFalse);
      expect(service.current.enabled, isFalse);
      expect(find.text('Фраза 1 из 3'), findsOneWidget);
    },
  );

  testWidgets('denied permission never starts native capture', (tester) async {
    final service = _VoiceService();
    await _show(tester, service, permission: () async => false);
    await tester.ensureVisible(find.text('Записать фразу'));
    await tester.tap(find.text('Записать фразу'));
    await tester.pumpAndSettle();
    expect(service.enrollCalls, 0);
    expect(find.textContaining('Разреши доступ'), findsOneWidget);
  });

  testWidgets('late permission grant cannot start recording in background', (
    tester,
  ) async {
    final permission = Completer<bool>();
    final service = _VoiceService();
    await _show(tester, service, permission: () => permission.future);
    await tester.ensureVisible(find.text('Записать фразу'));
    await tester.tap(find.text('Записать фразу'));
    await tester.pump();
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    addTearDown(
      () => tester.binding.handleAppLifecycleStateChanged(
        AppLifecycleState.resumed,
      ),
    );
    permission.complete(true);
    await tester.pumpAndSettle();
    expect(service.enrollCalls, 0);
    expect(
      find.text('Вернись в приложение и начни запись заново.'),
      findsOneWidget,
    );
  });

  testWidgets(
    'damaged protected profile allows deletion without re-enrollment bypass',
    (tester) async {
      final service = _VoiceService(
        current: const OwnerVoiceStatus(enabled: true),
      );
      await _show(tester, service);
      expect(find.text('Записать фразу'), findsNothing);
      expect(find.textContaining('Образец повреждён'), findsOneWidget);
      await tester.ensureVisible(find.text('Удалить образец голоса'));
      await tester.tap(find.text('Удалить образец голоса'));
      await tester.pumpAndSettle();
      expect(service.current.enabled, isFalse);
      expect(find.text('Записать фразу'), findsOneWidget);
    },
  );

  testWidgets(
    'short sample preserves enrollment progress with recovery message',
    (tester) async {
      final service = _VoiceService()..reject = true;
      await _show(tester, service);
      await tester.ensureVisible(find.text('Записать фразу'));
      await tester.tap(find.text('Записать фразу'));
      await tester.pumpAndSettle();
      expect(service.current.samples, 0);
      expect(find.text('Говори не меньше четырёх секунд.'), findsOneWidget);
    },
  );

  testWidgets('cancel discards late enrollment result', (tester) async {
    final service = _VoiceService()..pending = Completer<OwnerVoiceStatus>();
    await _show(tester, service);
    await tester.ensureVisible(find.text('Записать фразу'));
    await tester.tap(find.text('Записать фразу'));
    await tester.pump();
    await tester.ensureVisible(find.text('Отменить запись'));
    await tester.tap(find.text('Отменить запись'));
    await tester.pumpAndSettle();
    service.pending!.complete(
      const OwnerVoiceStatus(enrolled: true, samples: 3),
    );
    await tester.pumpAndSettle();
    expect(service.cancelCalls, 1);
    expect(find.text('Фраза 1 из 3'), findsOneWidget);
    expect(
      tester.widget<SwitchListTile>(find.byType(SwitchListTile)).onChanged,
      isNull,
    );
  });

  for (final width in [360.0, 390.0, 430.0]) {
    for (final dark in [false, true]) {
      testWidgets('enrollment fits width $width dark=$dark at text 150%', (
        tester,
      ) async {
        tester.view.physicalSize = Size(width, 920);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final boundary = GlobalKey();
        await tester.pumpWidget(
          MaterialApp(
            theme: dark ? buildTroikaTheme() : buildTroikaLightTheme(),
            builder: (context, child) => MediaQuery(
              data: MediaQuery.of(
                context,
              ).copyWith(textScaler: const TextScaler.linear(1.5)),
              child: RepaintBoundary(key: boundary, child: child!),
            ),
            home: OwnerVoiceScreen(service: _VoiceService()),
          ),
        );
        await tester.pumpAndSettle();
        Future<void> render(String state) async {
          final folder = Platform.environment['TROIKA_OWNER_VOICE_RENDERS'];
          if (folder == null) return;
          final paint =
              boundary.currentContext!.findRenderObject()!
                  as RenderRepaintBoundary;
          await tester.runAsync(() async {
            final image = await paint.toImage();
            final png = await image.toByteData(format: ui.ImageByteFormat.png);
            await Directory(folder).create(recursive: true);
            await File(
              '$folder/android-${dark ? 'dark' : 'light'}-${width.toInt()}-$state.png',
            ).writeAsBytes(png!.buffer.asUint8List());
            image.dispose();
          });
        }

        await render('top');
        await tester.scrollUntilVisible(find.text('Записать фразу'), 240);
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        await render('enroll');
      });
    }
  }
}
