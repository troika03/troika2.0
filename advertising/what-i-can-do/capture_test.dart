import 'dart:io';
import 'dart:ui' as ui;
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:troika_assistant/config/troika_config.dart';
import 'package:troika_assistant/theme/troika_theme.dart';
import 'package:troika_assistant/screens/chat_screen.dart';
import 'package:troika_assistant/screens/commands_screen.dart';
import 'package:troika_assistant/screens/history_screen.dart';
import 'package:troika_assistant/screens/capabilities_screen.dart';
import 'package:troika_assistant/screens/local_documents_screen.dart';
import 'package:troika_assistant/services/capability_service.dart';
import 'package:troika_assistant/services/assistant_service.dart';
import 'package:troika_assistant/services/troika_api_service.dart';
import 'package:troika_assistant/services/web_sources.dart';
import 'package:troika_assistant/widgets/troika_page.dart';

class DemoAssistant extends AssistantService {
  @override
  final List<ChatMessage> messages = [];
}
class DemoHistory extends TroikaApiService {
  @override
  Future<List<SessionSummary>> listSessions({int limit=50,int offset=0}) async =>
    ['Гитара на пятницу','Как подобрать струны','План на неделю'].map((title) =>
      SessionSummary(id:title,title:title,preview:title,messageCount:4,lastActive:1763481600)).toList();
}
class DemoCatalogue extends CapabilityService {
  @override
  Future<ExtensionCatalogue> loadCatalogue() async => const ExtensionCatalogue(
    skills:[CatalogueEntry(id:'creative/humanizer',title:'Живой текст',description:'Убирает шаблонные обороты.',category:'Творчество',connectable:true,connected:true)],
    mcp:[CatalogueEntry(id:'notion',title:'Notion',description:'Страницы Notion.',category:'Продуктивность',connect:'oauth',connectable:true,connected:false)],
    tools:[TroikaCapability(id:'web',title:'Поиск в интернете',description:'Находить информацию и источники.',enabled:true,available:true,skills:[],tools:[])]);
}
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('Capture catalogue, commands and demo conversations', (t) async {
    final folder=Directory(Platform.environment['TROIKA_OV_SCREENS']!)..createSync(recursive:true);
    final messenger=TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    for (final ch in ['com.llfbandit.record/messages','flutter_tts','xyz.luan/audioplayers.global','xyz.luan/audioplayers.global/events']) {
      messenger.setMockMethodCallHandler(MethodChannel(ch),(_) async=>null);
    }
    messenger.setMockMethodCallHandler(const MethodChannel('xyz.luan/audioplayers'),(call) async {
      if(call.method=='create') messenger.setMockMethodCallHandler(MethodChannel('xyz.luan/audioplayers/events/${(call.arguments as Map)['playerId']}'),(_) async=>null);
      return null;
    });
    for (final font in ['Golos Text','Roboto','Ahem','MaterialIcons']) {
      await (FontLoader(font)..addFont(rootBundle.load(font=='MaterialIcons'?'fonts/MaterialIcons-Regular.otf':'assets/fonts/GolosText-Variable.ttf'))).load();
    }
    SharedPreferences.setMockInitialValues({'troika_server_url':'https://example.invalid'}); await TroikaConfig.init();
    t.view.physicalSize=const Size(390,780);t.view.devicePixelRatio=1;
    final assistant=DemoAssistant();
    final key=GlobalKey();
    Future<void> show(Widget widget) async {
      await t.pumpWidget(ChangeNotifierProvider<AssistantService>.value(value:assistant,child:MaterialApp(debugShowCheckedModeBanner:false,
        theme:buildTroikaTheme(),builder:(c,child)=>RepaintBoundary(key:key,child:child!),home:widget)));
      await t.pumpAndSettle();
    }
    Future<void> shoot(String name) async {
      final render=key.currentContext!.findRenderObject() as RenderRepaintBoundary;
      // Material falls back to the test-only Ahem font on some route titles.
      InlineSpan brandFont(InlineSpan span) {
        if (span is! TextSpan) return span;
        final style = span.style ?? const TextStyle();
        return TextSpan(text:span.text,style:style.fontFamily=='MaterialIcons'?style:style.copyWith(fontFamily:'Golos Text'),
          children:span.children?.map(brandFont).toList());
      }
      void applyFont(RenderObject r) {
        if(r is RenderParagraph) r.text=brandFont(r.text);
        r.visitChildren(applyFont);
      }
      applyFont(render);
      await t.pump();
      await t.runAsync(() async {final im=await render.toImage(pixelRatio:3);final d=await im.toByteData(format:ui.ImageByteFormat.png);
        await File('${folder.path}/$name.png').writeAsBytes(d!.buffer.asUint8List());im.dispose();});
    }
    Widget chat()=>TroikaPage(appBar:AppBar(title:const Text('Текст')),body:const ChatScreen());
    void dialog(String q,String a){assistant.messages..clear()..add(ChatMessage(role:'user',text:q))..add(ChatMessage(role:'assistant',text:a));}
    dialog('Объясни, почему струна звучит.','Струна колеблется. Колебания передаются воздуху, а ухо воспринимает их как звук.');
    await show(chat());await shoot('talk');
    assistant.messages.addAll([ChatMessage(role:'user',text:'Короче.'),ChatMessage(role:'assistant',text:'Струна дрожит — ты слышишь звук.')]);
    await show(chat());await shoot('short');
    await show(HistoryScreen(api:DemoHistory()));await shoot('history');
    dialog('Где посмотреть, как образуется звук?','Звук распространяется волнами. Начни с раздела о звуковых волнах в учебнике OpenStax.');
    assistant.messages.last.webSources.apply(WebSourceActivity('found',[WebSource(Uri.parse('https://openstax.org/books/college-physics-2e/pages/17-1-sound'),'Sound · OpenStax','found')]));
    await show(chat());await t.tap(find.byType(ExpansionTile).first);await t.pumpAndSettle();await shoot('sources');
    await show(const LocalDocumentsScreen(initialPrompt:'создай документ План репетиции'));await shoot('doc');
    await show(const SizedBox.shrink());await show(const LocalDocumentsScreen(initialPresentation:true,initialPrompt:'создай презентацию Как устроен звук'));await shoot('slides');
    await show(const CommandsScreen());await shoot('commands');
    await t.drag(find.byType(ListView).first,const Offset(0,-300));await t.pumpAndSettle();await shoot('media');
    await show(CapabilitiesScreen(service:DemoCatalogue()));await shoot('skills');
    await t.tap(find.text('MCP').first);await t.pumpAndSettle();await shoot('mcp');
    await show(const SizedBox.shrink());assistant.dispose();await t.pumpAndSettle();
  });
}
