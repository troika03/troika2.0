import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:troika_assistant/config/troika_config.dart';
import 'package:troika_assistant/services/files_service.dart';
import 'package:troika_assistant/services/request_identity.dart';

Map<String, dynamic> _artifact(List<int> bytes, [String digit = 'c']) => {
  'id': 'delivery_${digit * 32}',
  'filename': 'test.pdf',
  'kind': 'pdf',
  'size': bytes.length,
  'sha256': sha256.convert(bytes).toString(),
  'created_at': 1.0,
};

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() async {
    SharedPreferences.setMockInitialValues({
      'troika_account_email': 'one@example.com',
      'troika_server_url': 'https://first.example.test',
      'troika_api_key': 'trk_live_synthetic_one',
      'troika_session_id': 'ses_one',
      'troika_session_key': 'ses_one',
      'troika_access_token_expires_at': DateTime.now()
          .add(const Duration(days: 1))
          .millisecondsSinceEpoch,
    });
    await TroikaConfig.init();
  });
  test(
    'durable local file and metadata exist before acknowledgement; offline reopen works',
    () async {
      final directory = await Directory.systemTemp.createTemp(
        'troika-file-delivery-test-',
      );
      addTearDown(() => directory.delete(recursive: true));
      final bytes = utf8.encode('%PDF-test');
      final artifact = {
        'id': 'delivery_${'a' * 32}',
        'filename': 'test.pdf',
        'kind': 'pdf',
        'size': bytes.length,
        'sha256': sha256.convert(bytes).toString(),
        'created_at': 1.0,
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
      service = FilesService(
        client: client,
        documentsDirectory: () async => directory,
      );
      final file = await service.receiveDeviceFile(artifact);
      expect(acknowledgements, 1);
      await service.receiveDeviceFile(
        artifact,
      ); // Retry after a lost server acknowledgement.
      expect(gets, 1);
      expect(acknowledgements, 2);
      final offline = MockClient(
        (_) async => throw const SocketException('offline'),
      );
      addTearDown(offline.close);
      final offlineService = FilesService(
        client: offline,
        documentsDirectory: () async => directory,
      );
      expect((await offlineService.list()).single.id, file.id);
      expect(await offlineService.deleteFile(file), isNull);
      expect(await service.localFiles(), isEmpty);
    },
  );
  test('bad digest is never acknowledged or committed locally', () async {
    final directory = await Directory.systemTemp.createTemp(
      'troika-file-digest-test-',
    );
    addTearDown(() => directory.delete(recursive: true));
    var acknowledged = false;
    final client = MockClient((request) async {
      if (request.method == 'POST') acknowledged = true;
      return http.Response('%PDF-test', 200);
    });
    addTearDown(client.close);
    final service = FilesService(
      client: client,
      documentsDirectory: () async => directory,
    );
    await expectLater(
      service.receiveDeviceFile({
        'id': 'delivery_${'b' * 32}',
        'kind': 'pdf',
        'size': 9,
        'sha256': 'wrong',
      }),
      throwsFormatException,
    );
    expect(acknowledged, isFalse);
    expect(await service.localFiles(), isEmpty);
  });

  test(
    'account switch during download never saves or acknowledges old bytes',
    () async {
      final directory = await Directory.systemTemp.createTemp(
        'troika-file-owner-',
      );
      addTearDown(() => directory.delete(recursive: true));
      final entered = Completer<void>();
      final release = Completer<void>();
      var acknowledgements = 0;
      final bytes = utf8.encode('%PDF-owner-fixture');
      final client = MockClient((request) async {
        if (request.method == 'POST') {
          acknowledgements++;
          return http.Response('', 200);
        }
        entered.complete();
        await release.future;
        return http.Response.bytes(bytes, 200);
      });
      addTearDown(client.close);
      final service = FilesService(
        client: client,
        documentsDirectory: () async => directory,
      );
      final pending = service.receiveDeviceFile(_artifact(bytes));
      final rejected = expectLater(
        pending,
        throwsA(isA<RequestIdentityChanged>()),
      );
      await entered.future;
      await TroikaConfig.saveAccount(
        email: 'two@example.com',
        token: 'trk_live_synthetic_two',
        homeSessionId: 'ses_two',
        replaceIdentity: true,
      );
      release.complete();
      await rejected;
      expect(acknowledgements, 0);
      expect(await service.localFiles(), isEmpty);
      expect(
        await directory.list(recursive: true).where((e) => e is File).isEmpty,
        isTrue,
      );
    },
  );

  test(
    'a recovery snapshot never starts downloads against a replacement origin',
    () async {
      final directory = await Directory.systemTemp.createTemp(
        'troika-file-recover-',
      );
      addTearDown(() => directory.delete(recursive: true));
      final entered = Completer<void>();
      final release = Completer<void>();
      final requests = <Uri>[];
      final client = MockClient((request) async {
        requests.add(request.url);
        if (request.url.path == '/v1/device-files') {
          entered.complete();
          await release.future;
          return http.Response(
            jsonEncode({
              'data': [_artifact(utf8.encode('%PDF-a'))],
            }),
            200,
          );
        }
        return http.Response('%PDF-a', 200);
      });
      addTearDown(client.close);
      final service = FilesService(
        client: client,
        documentsDirectory: () async => directory,
      );
      final pending = service.recoverPending();
      final rejected = expectLater(
        pending,
        throwsA(isA<RequestIdentityChanged>()),
      );
      await entered.future;
      TroikaConfig.serverUrl = 'https://replacement.example.test';
      release.complete();
      await rejected;
      expect(requests.map((uri) => uri.path), ['/v1/device-files']);
      expect(requests.single.host, 'first.example.test');
    },
  );

  test(
    'identity switch while finding local storage prevents any HTTP request',
    () async {
      final entered = Completer<void>();
      final release = Completer<Directory>();
      final directory = await Directory.systemTemp.createTemp(
        'troika-file-root-',
      );
      addTearDown(() => directory.delete(recursive: true));
      var requests = 0;
      final client = MockClient((_) async {
        requests++;
        return http.Response('%PDF-a', 200);
      });
      addTearDown(client.close);
      final service = FilesService(
        client: client,
        documentsDirectory: () {
          entered.complete();
          return release.future;
        },
      );
      final pending = service.receiveDeviceFile(
        _artifact(utf8.encode('%PDF-a')),
      );
      final rejected = expectLater(
        pending,
        throwsA(isA<RequestIdentityChanged>()),
      );
      await entered.future;
      TroikaConfig.serverUrl = 'https://replacement.example.test';
      release.complete(directory);
      await rejected;
      expect(requests, 0);
    },
  );

  test(
    'a failed old listing cannot fall back to files from the previous account',
    () async {
      final directory = await Directory.systemTemp.createTemp(
        'troika-file-list-',
      );
      addTearDown(() => directory.delete(recursive: true));
      final entered = Completer<void>();
      final release = Completer<void>();
      final bytes = utf8.encode('%PDF-list-fixture');
      final client = MockClient((request) async {
        if (request.url.path == '/v1/device-files') {
          return http.Response('{"data":[]}', 200);
        }
        if (request.url.path == '/v1/artifacts') {
          entered.complete();
          await release.future;
          throw const SocketException('offline');
        }
        return http.Response.bytes(bytes, 200);
      });
      addTearDown(client.close);
      final service = FilesService(
        client: client,
        documentsDirectory: () async => directory,
      );
      await service.receiveDeviceFile(_artifact(bytes));
      final pending = service.list();
      final rejected = expectLater(
        pending,
        throwsA(isA<RequestIdentityChanged>()),
      );
      await entered.future;
      await TroikaConfig.saveAccount(
        email: 'two@example.com',
        token: 'trk_live_synthetic_two',
        homeSessionId: 'ses_two',
        replaceIdentity: true,
      );
      release.complete();
      await rejected;
    },
  );

  test(
    'old local file handles cannot delete a file after origin replacement',
    () async {
      final directory = await Directory.systemTemp.createTemp(
        'troika-file-handle-',
      );
      addTearDown(() => directory.delete(recursive: true));
      final bytes = utf8.encode('%PDF-handle-fixture');
      final client = MockClient((_) async => http.Response.bytes(bytes, 200));
      addTearDown(client.close);
      final service = FilesService(
        client: client,
        documentsDirectory: () async => directory,
      );
      final file = await service.receiveDeviceFile(_artifact(bytes));
      TroikaConfig.serverUrl = 'https://replacement.example.test';
      expect(await service.deleteFile(file), isNotNull);
      expect(await File(file.localPath!).exists(), isTrue);
    },
  );

  test('file credentials never follow redirects', () async {
    final directory = await Directory.systemTemp.createTemp(
      'troika-file-redirect-',
    );
    addTearDown(() => directory.delete(recursive: true));
    final client = MockClient((request) async {
      expect(request.followRedirects, isFalse);
      return http.Response(
        '',
        307,
        headers: {'location': 'https://replacement.example.test'},
      );
    });
    addTearDown(client.close);
    final service = FilesService(
      client: client,
      documentsDirectory: () async => directory,
    );
    await expectLater(
      service.receiveDeviceFile(_artifact(utf8.encode('%PDF-a'))),
      throwsA(isA<HttpException>()),
    );
    expect(await service.localFiles(), isEmpty);
  });

  test('oversize artifact metadata is rejected before downloading', () async {
    var requests = 0;
    final client = MockClient((_) async {
      requests++;
      return http.Response('', 200);
    });
    addTearDown(client.close);
    final service = FilesService(client: client);
    await expectLater(
      service.receiveDeviceFile({
        ..._artifact(utf8.encode('%PDF-a')),
        'size': 50 * 1024 * 1024 + 1,
      }),
      throwsFormatException,
    );
    expect(requests, 0);
  });

  test(
    'token rotation for the same identity permits delivery and uses fresh ACK',
    () async {
      final directory = await Directory.systemTemp.createTemp(
        'troika-file-token-',
      );
      addTearDown(() => directory.delete(recursive: true));
      final bytes = utf8.encode('%PDF-token-fixture');
      var acknowledged = false;
      final client = MockClient((request) async {
        if (request.method == 'POST') {
          expect(
            request.headers['authorization'],
            'Bearer trk_live_synthetic_rotated',
          );
          acknowledged = true;
          return http.Response('', 200);
        }
        await TroikaConfig.saveAccount(
          email: 'one@example.com',
          token: 'trk_live_synthetic_rotated',
          homeSessionId: 'ses_one',
        );
        return http.Response.bytes(bytes, 200);
      });
      addTearDown(client.close);
      final service = FilesService(
        client: client,
        documentsDirectory: () async => directory,
      );
      final file = await service.receiveDeviceFile(_artifact(bytes));
      expect(acknowledged, isTrue);
      expect(await File(file.localPath!).readAsBytes(), bytes);
    },
  );

  for (final missing in [false, true]) {
    test(
      'retry repairs ${missing ? 'missing' : 'corrupt'} metadata before ACK',
      () async {
        final directory = await Directory.systemTemp.createTemp(
          'troika-file-repair-',
        );
        addTearDown(() => directory.delete(recursive: true));
        final bytes = utf8.encode('%PDF-repair-fixture');
        late FilesService service;
        var downloads = 0, acknowledgements = 0;
        final client = MockClient((request) async {
          if (request.method == 'POST') {
            final files = await service.localFiles();
            expect(files.single.name, 'test.pdf');
            expect(await File(files.single.localPath!).readAsBytes(), bytes);
            acknowledgements++;
            return http.Response('', 200);
          }
          downloads++;
          return http.Response.bytes(bytes, 200);
        });
        addTearDown(client.close);
        service = FilesService(
          client: client,
          documentsDirectory: () async => directory,
        );
        final file = await service.receiveDeviceFile(_artifact(bytes));
        final metadata = File('${file.localPath!}.metadata.json');
        if (missing) {
          await metadata.delete();
        } else {
          await metadata.writeAsString('{');
        }
        await service.receiveDeviceFile(_artifact(bytes));
        expect(acknowledgements, 2);
        expect(downloads, 1);
        expect((await service.localFiles()).single.id, file.id);
      },
    );
  }

  test(
    'a conflicting delivery never overwrites the existing local original',
    () async {
      final directory = await Directory.systemTemp.createTemp(
        'troika-file-version-',
      );
      addTearDown(() => directory.delete(recursive: true));
      final original = utf8.encode('%PDF-original-fixture');
      var downloads = 0, acknowledgements = 0;
      final client = MockClient((request) async {
        if (request.method == 'POST') {
          acknowledgements++;
        } else {
          downloads++;
        }
        return http.Response.bytes(original, 200);
      });
      addTearDown(client.close);
      final service = FilesService(
        client: client,
        documentsDirectory: () async => directory,
      );
      final file = await service.receiveDeviceFile(_artifact(original));
      await expectLater(
        service.receiveDeviceFile(_artifact(utf8.encode('%PDF-new-fixture'))),
        throwsFormatException,
      );
      expect(await File(file.localPath!).readAsBytes(), original);
      expect(downloads, 1);
      expect(acknowledgements, 1);
    },
  );
}
