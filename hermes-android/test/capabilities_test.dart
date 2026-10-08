import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:troika_assistant/config/troika_config.dart';
import 'package:troika_assistant/screens/capabilities_screen.dart';
import 'package:troika_assistant/services/capability_service.dart';
import 'package:troika_assistant/theme/troika_theme.dart';

const web = TroikaCapability(
  id: 'web',
  title: 'Поиск в интернете',
  description: 'Находить информацию и источники.',
  enabled: true,
  available: true,
  skills: ['Искать информацию и приводить ссылки.'],
  tools: [
    CapabilityTool(id: 'web_search', title: 'Поиск страниц', available: true)
  ],
);

Map<String, dynamic> catalogue({bool enabled = true}) => {
      'object': 'troika.capabilities',
      'capabilities': [
        {
          'id': 'web',
          'title': web.title,
          'description': web.description,
          'available': true,
          'enabled': enabled,
          'skills': [
            {'description': web.skills.first}
          ],
          'tools': [
            {'id': 'web_search', 'title': 'Поиск страниц', 'available': true}
          ],
        }
      ],
    };

class StubService extends CapabilityService {
  bool failLoad = false;
  bool failSave = false;
  int saves = 0;
  List<TroikaCapability> items = [web];
  @override
  Future<List<TroikaCapability>> load() async {
    if (failLoad) throw const CapabilityException('Нет соединения.');
    return items;
  }

  @override
  Future<List<TroikaCapability>> setEnabled(String id, bool enabled) async {
    saves++;
    if (failSave) throw const CapabilityException('Изменение не сохранено.');
    items = [
      TroikaCapability(
          id: web.id,
          title: web.title,
          description: web.description,
          enabled: enabled,
          available: true,
          skills: web.skills,
          tools: web.tools)
    ];
    return items;
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(() async {
    if (Platform.environment['TROIKA_CAPTURE_UI'] == '1' &&
        Platform.isWindows) {
      final bytes = await File('C:/Windows/Fonts/segoeui.ttf').readAsBytes();
      final loader = FontLoader('Inter')
        ..addFont(Future.value(ByteData.view(bytes.buffer)));
      await loader.load();
      final icons = await File(
        'C:/src/flutter/bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf',
      ).readAsBytes();
      await (FontLoader('MaterialIcons')
            ..addFont(Future.value(ByteData.view(icons.buffer))))
          .load();
    }
  });

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    await TroikaConfig.init();
  });

  test('service sends an owner-authenticated patch and reads server state',
      () async {
    final requests = <http.Request>[];
    final service = CapabilityService(
      refreshSession: () async => true,
      client: MockClient((request) async {
        requests.add(request);
        return http.Response(
            jsonEncode(catalogue(enabled: request.method != 'PATCH')), 200,
            headers: {'content-type': 'application/json; charset=utf-8'});
      }),
    );
    expect((await service.load()).single.enabled, isTrue);
    expect((await service.setEnabled('web', false)).single.enabled, isFalse);
    expect(requests.last.url.path, '/v1/account/capabilities');
    expect(jsonDecode(requests.last.body), {
      'enabled': {'web': false}
    });
  });

  test('old backend and invalid catalogue never report a saved change',
      () async {
    for (final response in [
      http.Response('', 404),
      http.Response('{}', 200),
      http.Response('', 503)
    ]) {
      final service = CapabilityService(
          refreshSession: () async => true,
          client: MockClient((_) async => response));
      await expectLater(service.setEnabled('web', false),
          throwsA(isA<CapabilityException>()));
    }
  });

  test('an expired session prevents a network mutation', () async {
    var called = false;
    final service = CapabilityService(
        refreshSession: () async => false,
        client: MockClient((_) async {
          called = true;
          return http.Response('', 200);
        }));
    await expectLater(
        service.setEnabled('web', false), throwsA(isA<CapabilityException>()));
    expect(called, isFalse);
  });

  testWidgets(
      'plugins switch saves; skill and tool views reflect disabled state',
      (tester) async {
    final service = StubService();
    addTearDown(service.dispose);
    await tester.pumpWidget(MaterialApp(
        theme: buildTroikaTheme(), home: CapabilitiesScreen(service: service)));
    await tester.pumpAndSettle();
    await tester.tap(find.byType(Switch));
    await tester.pumpAndSettle();
    expect(service.saves, 1);
    expect(tester.widget<Switch>(find.byType(Switch)).value, isFalse);
    await tester.tap(find.text('Навыки'));
    await tester.pumpAndSettle();
    expect(find.text(web.skills.first), findsOneWidget);
    expect(find.text('Выключено'), findsOneWidget);
    await tester.tap(find.text('Инструменты'));
    await tester.pumpAndSettle();
    expect(find.text('Поиск страниц'), findsOneWidget);
    expect(find.text('Плагин выключен'), findsOneWidget);
  });

  testWidgets('failed save preserves switch; load failure offers retry',
      (tester) async {
    final service = StubService()..failSave = true;
    addTearDown(service.dispose);
    await tester
        .pumpWidget(MaterialApp(home: CapabilitiesScreen(service: service)));
    await tester.pumpAndSettle();
    await tester.tap(find.byType(Switch));
    await tester.pumpAndSettle();
    expect(tester.widget<Switch>(find.byType(Switch)).value, isTrue);
    expect(find.text('Изменение не сохранено.'), findsOneWidget);
    service.failLoad = true;
    await tester.tap(find.byTooltip('Обновить'));
    await tester.pumpAndSettle();
    expect(find.text('Нет соединения.'), findsOneWidget);
    service.failLoad = false;
    await tester.tap(find.text('Повторить'));
    await tester.pumpAndSettle();
    expect(find.byType(Switch), findsOneWidget);
  });

  for (final dark in [false, true]) {
    testWidgets('page fits narrow screen and large text, dark=$dark',
        (tester) async {
      tester.view.physicalSize = const Size(360, 800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final service = StubService();
      addTearDown(service.dispose);
      final captureKey = GlobalKey();
      await tester.pumpWidget(MaterialApp(
        theme: buildTroikaLightTheme().copyWith(
          textTheme:
              buildTroikaLightTheme().textTheme.apply(fontFamily: 'Inter'),
          primaryTextTheme: buildTroikaLightTheme()
              .primaryTextTheme
              .apply(fontFamily: 'Inter'),
        ),
        darkTheme: buildTroikaTheme().copyWith(
          textTheme: buildTroikaTheme().textTheme.apply(fontFamily: 'Inter'),
          primaryTextTheme:
              buildTroikaTheme().primaryTextTheme.apply(fontFamily: 'Inter'),
        ),
        themeMode: dark ? ThemeMode.dark : ThemeMode.light,
        builder: (context, child) => MediaQuery(
            data: MediaQuery.of(context)
                .copyWith(textScaler: const TextScaler.linear(1.5)),
            child: RepaintBoundary(key: captureKey, child: child!)),
        home: CapabilitiesScreen(service: service),
      ));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      if (Platform.environment['TROIKA_CAPTURE_UI'] == '1') {
        final boundary = captureKey.currentContext!.findRenderObject()!
            as RenderRepaintBoundary;
        await tester.runAsync(() async {
          final image = await boundary.toImage(pixelRatio: 1);
          final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
          await File('../_logs/capabilities-${dark ? "dark" : "light"}.png')
              .writeAsBytes(bytes!.buffer.asUint8List());
          image.dispose();
        });
      }
    });
  }
}
