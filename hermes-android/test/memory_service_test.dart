import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:troika_assistant/config/troika_config.dart';
import 'package:troika_assistant/services/memory_service.dart';
import 'package:troika_assistant/services/troika_api_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    await TroikaConfig.init();
  });
  test('loads account preference and distinguishes automatic records',
      () async {
    final service = MemoryService(client: MockClient((request) async {
      expect(request.url.path, '/v1/memories');
      return http.Response(
          json.encode({
            'preferences': {'automatic_enabled': true},
            'memories': [
              {
                'id': 'mem_auto',
                'title': 'Город',
                'content': 'Я живу в Казани.',
                'source': 'automatic'
              },
              {'id': 'mem_manual', 'title': 'Язык', 'content': 'Русский'},
            ],
          }),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'});
    }));
    final snapshot = await service.load();
    expect(snapshot.automaticEnabled, isTrue);
    expect(snapshot.supportsAutomatic, isTrue);
    expect(snapshot.automaticIds, {'mem_auto'});
    expect(snapshot.memories.length, 2);
    service.dispose();
  });

  test('old server keeps manual records without promising automatic memory',
      () {
    final snapshot = TroikaMemorySnapshot.fromJson({'memories': []});
    expect(snapshot.supportsAutomatic, isFalse);
    expect(snapshot.automaticEnabled, isFalse);
  });

  test('setting must be acknowledged by the server', () async {
    final service = MemoryService(client: MockClient((request) async {
      expect(request.method, 'PUT');
      expect(request.url.path, '/v1/memory-preferences');
      expect(json.decode(request.body), {'automatic_enabled': true});
      return http.Response('{"automatic_enabled":false}', 200);
    }));
    await expectLater(
        service.setAutomaticEnabled(true), throwsA(isA<TroikaApiException>()));
    service.dispose();
  });

  test('server failure is not reported as a saved setting', () async {
    final service =
        MemoryService(client: MockClient((_) async => http.Response('', 503)));
    await expectLater(
        service.setAutomaticEnabled(true), throwsA(isA<TroikaApiException>()));
    service.dispose();
  });
}
