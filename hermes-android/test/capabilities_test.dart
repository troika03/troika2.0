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
    CapabilityTool(id: 'web_search', title: 'Поиск страниц', available: true),
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
        {'description': web.skills.first},
      ],
      'tools': [
        {'id': 'web_search', 'title': 'Поиск страниц', 'available': true},
      ],
    },
  ],
};

const skill = CatalogueEntry(
  id: 'creative/humanizer',
  title: 'Живой текст',
  icon: 'design',
  description: 'Убирает шаблонные обороты.',
  category: 'Творчество',
  connectable: true,
  connected: false,
);
const localSkill = CatalogueEntry(
  id: 'apple/apple-notes',
  title: 'apple-notes',
  icon: 'device',
  description: 'Manage Apple Notes via memo CLI.',
  category: 'Apple',
  connectable: false,
  connected: false,
  reason: 'Нужны программы или ключи, которых нет в облаке Тройки.',
);
const github = CatalogueEntry(
  id: 'github',
  title: 'GitHub',
  icon: 'code',
  description: 'Репозитории и задачи.',
  category: 'Разработка',
  connectable: true,
  connected: false,
  connect: 'token',
  tokenName: 'Personal access token GitHub',
  tokenHelp: 'https://github.com/settings/personal-access-tokens',
);
const notion = CatalogueEntry(
  id: 'notion',
  title: 'Notion',
  icon: 'tasks',
  description: 'Страницы Notion.',
  category: 'Продуктивность',
  connectable: true,
  connected: false,
  connect: 'oauth',
);
const deepwiki = CatalogueEntry(
  id: 'deepwiki',
  title: 'DeepWiki',
  icon: 'code',
  description: 'Документация по публичным репозиториям GitHub.',
  category: 'Разработка',
  connectable: true,
  connected: false,
  homepage: 'https://mcp.deepwiki.com/mcp',
);
const linear = CatalogueEntry(
  id: 'linear',
  title: 'Linear',
  icon: 'tasks',
  description: 'Find, create, and update Linear issues.',
  category: 'remote',
  connectable: false,
  connected: false,
  reason: 'Нужен вход в аккаунт сервиса.',
);

class StubService extends CapabilityService {
  final connected = <String>{};
  final tokens = <String, String>{};
  int polls = 0;

  @override
  Future<ServiceConnectStart> connectService(String id, {String? token}) async {
    if (token != null) {
      tokens[id] = token;
      connected.add(id);
      return const ServiceConnectStart('connected', '', null);
    }
    return ServiceConnectStart(
      'waiting',
      'flow-1',
      Uri.parse('https://auth.example/authorize'),
    );
  }

  @override
  Future<String> serviceFlowStatus(String flow) async {
    polls++;
    if (polls < 2) return 'waiting';
    connected.add('notion');
    return 'connected';
  }

  bool failLoad = false;
  bool failSave = false;
  int saves = 0;
  List<TroikaCapability> items = [web];
  List<CatalogueEntry> skills = [skill, localSkill];
  ExtensionCatalogue get catalogue => ExtensionCatalogue(
    skills: skills,
    mcp: [
      for (final item in mcp)
        connected.contains(item.id)
            ? CatalogueEntry(
                id: item.id,
                title: item.title,
                description: item.description,
                category: item.category,
                connectable: item.connectable,
                connected: true,
                connect: item.connect,
              )
            : item,
    ],
    tools: items,
  );
  List<CatalogueEntry> mcp = [deepwiki, linear];
  String? lastMcp;

  @override
  Future<ExtensionCatalogue> setMcpConnected(String id, bool connected) async {
    saves++;
    lastMcp = '$id=$connected';
    mcp = [
      for (final item in mcp)
        item.id == id
            ? CatalogueEntry(
                id: item.id,
                title: item.title,
                description: item.description,
                category: item.category,
                connectable: item.connectable,
                connected: connected,
                homepage: item.homepage,
              )
            : item,
    ];
    return catalogue;
  }

  @override
  Future<ExtensionCatalogue> loadCatalogue() async {
    if (failLoad) throw const CapabilityException('Нет соединения.');
    return catalogue;
  }

  @override
  Future<ExtensionCatalogue> setToolEnabled(String id, bool enabled) async {
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
        tools: web.tools,
      ),
    ];
    return catalogue;
  }

  @override
  Future<ExtensionCatalogue> setSkillConnected(
    String id,
    bool connected,
  ) async {
    saves++;
    if (failSave) throw const CapabilityException('Изменение не сохранено.');
    skills = [
      for (final item in skills)
        item.id == id
            ? CatalogueEntry(
                id: item.id,
                title: item.title,
                description: item.description,
                category: item.category,
                connectable: item.connectable,
                connected: connected,
              )
            : item,
    ];
    return catalogue;
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
      await (FontLoader(
        'MaterialIcons',
      )..addFont(Future.value(ByteData.view(icons.buffer)))).load();
    }
  });

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    await TroikaConfig.init();
  });

  test(
    'service sends an owner-authenticated patch and reads server state',
    () async {
      final requests = <http.Request>[];
      final service = CapabilityService(
        refreshSession: () async => true,
        client: MockClient((request) async {
          requests.add(request);
          return http.Response(
            jsonEncode(catalogue(enabled: request.method != 'PATCH')),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }),
      );
      expect((await service.load()).single.enabled, isTrue);
      expect((await service.setEnabled('web', false)).single.enabled, isFalse);
      expect(requests.last.url.path, '/v1/account/capabilities');
      expect(jsonDecode(requests.last.body), {
        'enabled': {'web': false},
      });
    },
  );

  test(
    'old backend and invalid catalogue never report a saved change',
    () async {
      for (final response in [
        http.Response('', 404),
        http.Response('{}', 200),
        http.Response('', 503),
      ]) {
        final service = CapabilityService(
          refreshSession: () async => true,
          client: MockClient((_) async => response),
        );
        await expectLater(
          service.setEnabled('web', false),
          throwsA(isA<CapabilityException>()),
        );
      }
    },
  );

  test('an expired session prevents a network mutation', () async {
    var called = false;
    final service = CapabilityService(
      refreshSession: () async => false,
      client: MockClient((_) async {
        called = true;
        return http.Response('', 200);
      }),
    );
    await expectLater(
      service.setEnabled('web', false),
      throwsA(isA<CapabilityException>()),
    );
    expect(called, isFalse);
  });

  test(
    'extension catalogue patches skills and falls back on old servers',
    () async {
      final requests = <http.Request>[];
      final service = CapabilityService(
        refreshSession: () async => true,
        client: MockClient((request) async {
          requests.add(request);
          return http.Response(
            jsonEncode({
              'object': 'troika.extensions',
              'skills': [
                {
                  'id': skill.id,
                  'title': skill.title,
                  'description': skill.description,
                  'category_title': 'Творчество',
                  'connectable': true,
                  'connected': request.method == 'PATCH',
                  'reason': '',
                },
              ],
              'mcp': [],
              'tools': catalogue()['capabilities'],
            }),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }),
      );
      expect((await service.loadCatalogue()).skills!.single.connected, isFalse);
      final saved = await service.setSkillConnected(skill.id, true);
      expect(saved.skills!.single.connected, isTrue);
      expect(requests.last.url.path, '/v1/account/extensions');
      expect(jsonDecode(requests.last.body), {
        'skills': {skill.id: true},
      });
      final old = CapabilityService(
        refreshSession: () async => true,
        client: MockClient(
          (request) async => request.url.path == '/v1/account/extensions'
              ? http.Response('', 404)
              : http.Response(
                  jsonEncode(catalogue()),
                  200,
                  headers: {'content-type': 'application/json; charset=utf-8'},
                ),
        ),
      );
      final fallback = await old.loadCatalogue();
      expect(fallback.skills, isNull);
      expect(fallback.tools.single.id, 'web');
      await expectLater(
        old.setSkillConnected(skill.id, true),
        throwsA(isA<CapabilityException>()),
      );
      final denied = CapabilityService(
        refreshSession: () async => true,
        client: MockClient((_) async => http.Response('', 403)),
      );
      await expectLater(
        denied.setSkillConnected('apple/apple-notes', true),
        throwsA(isA<CapabilityException>()),
      );
    },
  );

  testWidgets('skills connect after confirmation; search and MCP reasons', (
    tester,
  ) async {
    final service = StubService();
    addTearDown(service.dispose);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildTroikaTheme(),
        home: CapabilitiesScreen(service: service),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Живой текст'), findsOneWidget);
    expect(find.text(localSkill.reason), findsOneWidget);
    await tester.tap(find.text('Подключить'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Отмена'));
    await tester.pumpAndSettle();
    expect(service.saves, 0);
    await tester.tap(find.text('Подключить'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Подключить').last);
    await tester.pumpAndSettle();
    expect(service.saves, 1);
    expect(find.text('Отключить'), findsOneWidget);
    expect(find.text('Скиллы · 1'), findsOneWidget);
    await tester.enterText(find.byType(TextField), 'apple');
    await tester.pumpAndSettle();
    expect(find.text('Живой текст'), findsNothing);
    expect(find.text('apple-notes'), findsOneWidget);
    await tester.tap(find.text('MCP'));
    await tester.pumpAndSettle();
    expect(find.text('Linear'), findsOneWidget);
    expect(find.text(linear.reason), findsOneWidget);
    // A reviewed cloud server connects after a confirmation naming its host.
    await tester.tap(find.widgetWithText(FilledButton, 'Подключить').first);
    await tester.pumpAndSettle();
    expect(find.textContaining('mcp.deepwiki.com'), findsOneWidget);
    await tester.tap(find.widgetWithText(FilledButton, 'Подключить').last);
    await tester.pumpAndSettle();
    expect(service.lastMcp, 'deepwiki=true');
    expect(find.text('MCP · 1'), findsOneWidget);
  });

  testWidgets('account services connect by token or browser sign-in', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(800, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final opened = <Uri>[];
    CapabilitiesScreen.openUrl = (uri) async {
      opened.add(uri);
      return true;
    };
    addTearDown(() => CapabilitiesScreen.openUrl = (uri) async => true);
    final service = StubService()..mcp = [github, notion];
    addTearDown(service.dispose);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildTroikaTheme(),
        home: CapabilitiesScreen(service: service),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('MCP'));
    await tester.pumpAndSettle();
    // Token: entered in an obscured field, never shown back.
    await tester.tap(find.text('Ввести токен'));
    await tester.pumpAndSettle();
    expect(
      tester.widget<TextField>(find.byType(TextField).last).obscureText,
      isTrue,
    );
    await tester.enterText(find.byType(TextField).last, 'github_pat_example');
    await tester.tap(find.widgetWithText(FilledButton, 'Подключить').last);
    await tester.pumpAndSettle();
    expect(service.tokens['github'], 'github_pat_example');
    expect(find.text('github_pat_example'), findsNothing);
    expect(find.text('MCP · 1'), findsOneWidget);
    // OAuth: confirmation, browser, then polling until connected.
    ScaffoldMessenger.of(
      tester.element(find.byType(Scaffold).first),
    ).hideCurrentSnackBar();
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('Войти').first);
    await tester.tap(find.text('Войти').first);
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Войти').last);
    await tester.pump();
    await tester.pump(const Duration(seconds: 2));
    await tester.pump(const Duration(seconds: 2));
    await tester.pumpAndSettle();
    expect(opened.single.host, 'auth.example');
    expect(service.connected, containsAll(['github', 'notion']));
  });

  testWidgets('free and plus see skills and MCP as a Pro feature', (
    tester,
  ) async {
    final service = _ProLockedService();
    addTearDown(service.dispose);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildTroikaTheme(),
        home: CapabilitiesScreen(service: service),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.textContaining('после перехода на Pro'), findsOneWidget);
    expect(find.text('Подключить'), findsNothing);
    await tester.tap(find.text('MCP'));
    await tester.pumpAndSettle();
    expect(find.textContaining('после перехода на Pro'), findsOneWidget);
    expect(find.text('Ввести токен'), findsNothing);
  });

  testWidgets('tool switch saves and reflects disabled tools', (tester) async {
    final service = StubService();
    addTearDown(service.dispose);
    await tester.pumpWidget(
      MaterialApp(
        theme: buildTroikaTheme(),
        home: CapabilitiesScreen(service: service),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('Инструменты'));
    await tester.pumpAndSettle();
    expect(find.text('Поиск страниц'), findsOneWidget);
    await tester.tap(find.byType(Switch));
    await tester.pumpAndSettle();
    expect(service.saves, 1);
    expect(tester.widget<Switch>(find.byType(Switch)).value, isFalse);
  });

  testWidgets('failed save preserves switch; load failure offers retry', (
    tester,
  ) async {
    final service = StubService()..failSave = true;
    addTearDown(service.dispose);
    await tester.pumpWidget(
      MaterialApp(home: CapabilitiesScreen(service: service)),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('Инструменты'));
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
    // The selected tab survives a reload.
    expect(find.text('Поиск страниц'), findsOneWidget);
  });

  for (final dark in [false, true]) {
    testWidgets('page fits narrow screen and large text, dark=$dark', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(360, 800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final service = StubService();
      addTearDown(service.dispose);
      final captureKey = GlobalKey();
      await tester.pumpWidget(
        MaterialApp(
          theme: buildTroikaLightTheme().copyWith(
            textTheme: buildTroikaLightTheme().textTheme.apply(
              fontFamily: 'Inter',
            ),
            primaryTextTheme: buildTroikaLightTheme().primaryTextTheme.apply(
              fontFamily: 'Inter',
            ),
          ),
          darkTheme: buildTroikaTheme().copyWith(
            textTheme: buildTroikaTheme().textTheme.apply(fontFamily: 'Inter'),
            primaryTextTheme: buildTroikaTheme().primaryTextTheme.apply(
              fontFamily: 'Inter',
            ),
          ),
          themeMode: dark ? ThemeMode.dark : ThemeMode.light,
          builder: (context, child) => MediaQuery(
            data: MediaQuery.of(
              context,
            ).copyWith(textScaler: const TextScaler.linear(1.5)),
            child: RepaintBoundary(key: captureKey, child: child!),
          ),
          home: CapabilitiesScreen(service: service),
        ),
      );
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      Future<void> capture(String name) async {
        if (Platform.environment['TROIKA_CAPTURE_UI'] != '1') return;
        final boundary =
            captureKey.currentContext!.findRenderObject()!
                as RenderRepaintBoundary;
        await tester.runAsync(() async {
          final image = await boundary.toImage(pixelRatio: 1);
          final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
          await File(
            '../_logs/$name-${dark ? "dark" : "light"}.png',
          ).writeAsBytes(bytes!.buffer.asUint8List());
          image.dispose();
        });
      }

      await capture('capabilities');
      await tester.tap(find.text('MCP'));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      await capture('capabilities-mcp');
    });
  }
}

class _ProLockedService extends StubService {
  @override
  Future<ExtensionCatalogue> loadCatalogue() async => ExtensionCatalogue(
    extensionsAllowed: false,
    skills: const [
      CatalogueEntry(
        id: 'creative/humanizer',
        title: 'Живой текст',
        description: 'Убирает шаблонные обороты.',
        connectable: false,
        connected: false,
        reason: 'Скиллы и MCP доступны в тарифе Pro.',
      ),
    ],
    mcp: const [
      CatalogueEntry(
        id: 'github',
        title: 'GitHub',
        description: 'Репозитории.',
        connectable: false,
        connected: false,
        connect: 'token',
        reason: 'Скиллы и MCP доступны в тарифе Pro.',
      ),
    ],
    tools: items,
  );
}
