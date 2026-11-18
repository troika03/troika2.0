import 'dart:convert';
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
import 'package:troika_assistant/services/troika_api_service.dart';
import 'package:troika_assistant/theme/troika_theme.dart';

class StoryAssistant extends AssistantService {
  final turns = <ChatMessage>[];
  @override
  List<ChatMessage> get messages => List.unmodifiable(turns);
  void addTurn(ChatMessage turn) {
    turns.add(turn);
    notifyListeners();
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('Capture real Android widgets with the commercial dialogue', (tester) async {
    final project = Directory(Platform.environment['TROIKA_AD_ROOT']!);
    final output = Directory('${project.path}/local/screens')..createSync(recursive: true);
    final lines = jsonDecode(File('${project.path}/story.json').readAsStringSync()) as List;
    final messenger = TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    for (final ch in ['com.llfbandit.record/messages','flutter_tts','xyz.luan/audioplayers.global','xyz.luan/audioplayers.global/events']) {
      messenger.setMockMethodCallHandler(MethodChannel(ch), (_) async => null);
    }
    messenger.setMockMethodCallHandler(const MethodChannel('xyz.luan/audioplayers'), (call) async {
      if (call.method == 'create') {
        final id = (call.arguments as Map)['playerId'];
        messenger.setMockMethodCallHandler(MethodChannel('xyz.luan/audioplayers/events/$id'), (_) async => null);
      }
      return null;
    });
    for (final entry in {'Golos Text':'assets/fonts/GolosText-Variable.ttf','Roboto':'assets/fonts/GolosText-Variable.ttf','Ahem':'assets/fonts/GolosText-Variable.ttf','Roboto_2018':'assets/fonts/GolosText-Variable.ttf','MaterialIcons':'fonts/MaterialIcons-Regular.otf'}.entries) {
      await (FontLoader(entry.key)..addFont(rootBundle.load(entry.value))).load();
    }
    SharedPreferences.setMockInitialValues({'troika_server_url':'https://example.invalid'});
    await TroikaConfig.init();
    tester.view.physicalSize = const Size(390, 780);
    tester.view.devicePixelRatio = 1;
    final assistant = StoryAssistant();
    final boundary = GlobalKey();
    await tester.pumpWidget(ChangeNotifierProvider<AssistantService>.value(value:assistant,
      child:MaterialApp(theme:buildTroikaTheme(), debugShowCheckedModeBanner:false,
        builder:(ctx,child)=>MediaQuery(data:MediaQuery.of(ctx).copyWith(disableAnimations:true),
          child:RepaintBoundary(key:boundary,child:child!)),
        home:const HomeScreen(windowsShellOverride:false))));
    await tester.pumpAndSettle();
    Future<void> save(String name) async {
      final render = boundary.currentContext!.findRenderObject()! as RenderRepaintBoundary;
      await tester.runAsync(() async {
        final image = await render.toImage(pixelRatio: 4);
        final data = await image.toByteData(format: ui.ImageByteFormat.png);
        await File('${output.path}/$name.png').writeAsBytes(data!.buffer.asUint8List());
        image.dispose();
      });
      expect(tester.takeException(), isNull);
    }
    await save('home');
    await tester.tap(find.byTooltip('Текст').first);
    await tester.pumpAndSettle();
    for (var i = 0; i < 4; i++) {
      assistant.addTurn(ChatMessage(role:lines[i][0]=='user'?'user':'assistant',text:lines[i][1],time:DateTime(2026,11,18,19,22)));
      await tester.pumpAndSettle();
      await save('chat-$i');
    }
    await tester.pumpWidget(const SizedBox.shrink());
    assistant.dispose();
    await tester.pumpAndSettle();
    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
  });
}
