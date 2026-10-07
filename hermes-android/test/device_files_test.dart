import 'dart:convert';
import 'dart:io';
import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:troika_assistant/config/troika_config.dart';
import 'package:troika_assistant/services/files_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() async {
    SharedPreferences.setMockInitialValues(
        {'troika_account_email': 'one@example.com'});
    await TroikaConfig.init();
  });
  test(
      'durable local file and metadata exist before acknowledgement; offline reopen works',
      () async {
    final directory =
        await Directory.systemTemp.createTemp('troika-file-delivery-test-');
    addTearDown(() => directory.delete(recursive: true));
    final bytes = utf8.encode('%PDF-test');
    final artifact = {
      'id': 'delivery_${'a' * 32}',
      'filename': 'test.pdf',
      'kind': 'pdf',
      'size': bytes.length,
      'sha256': sha256.convert(bytes).toString(),
      'created_at': 1.0
    };
    late FilesService service;
    var gets = 0;
    var acknowledgements = 0;
    final client = MockClient((request) async {
      if (request.method == 'POST') {
        acknowledgements++;
        final local = await service.localFiles();
        expect(local.length, 1);
        expect(await File(local.single.localPath!).readAsBytes(), bytes);
        return http.Response('', 200);
      }
      gets++;
      return http.Response.bytes(bytes, 200);
    });
    addTearDown(client.close);
    service =
        FilesService(client: client, documentsDirectory: () async => directory);
    final file = await service.receiveDeviceFile(artifact);
    expect(acknowledgements, 1);
    await service.receiveDeviceFile(
        artifact); // Retry after a lost server acknowledgement.
    expect(gets, 1);
    expect(acknowledgements, 2);
    final offline =
        MockClient((_) async => throw const SocketException('offline'));
    addTearDown(offline.close);
    final offlineService = FilesService(
        client: offline, documentsDirectory: () async => directory);
    expect((await offlineService.list()).single.id, file.id);
    expect(await offlineService.deleteFile(file), isNull);
    expect(await service.localFiles(), isEmpty);
  });
  test('bad digest is never acknowledged or committed locally', () async {
    final directory =
        await Directory.systemTemp.createTemp('troika-file-digest-test-');
    addTearDown(() => directory.delete(recursive: true));
    var acknowledged = false;
    final client = MockClient((request) async {
      if (request.method == 'POST') acknowledged = true;
      return http.Response('%PDF-test', 200);
    });
    addTearDown(client.close);
    final service =
        FilesService(client: client, documentsDirectory: () async => directory);
    await expectLater(
        service.receiveDeviceFile({
          'id': 'delivery_${'b' * 32}',
          'kind': 'pdf',
          'size': 9,
          'sha256': 'wrong'
        }),
        throwsFormatException);
    expect(acknowledged, isFalse);
    expect(await service.localFiles(), isEmpty);
  });
}
