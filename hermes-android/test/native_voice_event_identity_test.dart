import 'dart:async';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:troika_assistant/config/troika_config.dart';
import 'package:troika_assistant/services/wake_word_service.dart';

const _channel = MethodChannel('com.troika.hermes/background');

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  final services = <WakeWordService>[];

  Future<void> configure({
    String origin = 'https://voice.example.test',
    String owner = 'first@example.test',
    String credential = 'trk_live_synthetic_first',
    String session = 'ses_first',
    int generation = 7,
  }) async {
    SharedPreferences.setMockInitialValues({
      'troika_server_url': origin,
      'troika_account_email': owner,
      'troika_api_key': credential,
      'troika_session_id': session,
      'troika_session_key': session,
      'troika_native_identity_revision': generation,
      'troika_hosted_endpoint_migration_version': 2,
    });
    await TroikaConfig.init();
  }

  Map<String, Object> identity() => {
    'version': 1,
    'origin': TroikaConfig.serverUrl,
    'owner': TroikaConfig.accountEmail,
    'session_id': TroikaConfig.sessionId,
    'session_key': TroikaConfig.sessionKey,
    'native_generation': TroikaConfig.nativeIdentityRevision,
    'signed_in': TroikaConfig.signedIn,
  };

  Future<void> emit(Map<String, Object?> payload) async {
    final completed = Completer<void>();
    await messenger.handlePlatformMessage(
      _channel.name,
      const StandardMethodCodec().encodeMethodCall(
        MethodCall('voice_message', payload),
      ),
      (_) => completed.complete(),
    );
    await completed.future.timeout(const Duration(seconds: 2));
  }

  Future<WakeWordService> start(
    List<String> received, {
    Future<void> Function()? reload,
  }) async {
    final service = WakeWordService(reloadAccountSession: reload)
      ..onVoiceMessage = (role, content) => received.add('$role:$content');
    services.add(service);
    await service.startListening();
    return service;
  }

  setUp(() async {
    messenger.setMockMethodCallHandler(_channel, (_) async => true);
    await configure();
  });
  tearDown(() async {
    for (final service in services) {
      await service.stopListening();
    }
    services.clear();
    messenger.setMockMethodCallHandler(_channel, null);
  });

  test(
    'matching hosted user and assistant events reach the callback once',
    () async {
      final received = <String>[];
      await start(received);
      final scope = identity();
      await emit({
        'role': 'user',
        'content': 'Synthetic question',
        'identity': scope,
      });
      await emit({
        'role': 'assistant',
        'content': 'Synthetic reply',
        'identity': scope,
      });
      expect(received, [
        'user:Synthetic question',
        'assistant:Synthetic reply',
      ]);
    },
  );

  for (final role in ['user', 'assistant']) {
    test('queued $role event cannot cross account replacement', () async {
      final received = <String>[];
      await start(received);
      final oldScope = identity();
      await configure(
        owner: 'second@example.test',
        credential: 'trk_live_synthetic_second',
        session: 'ses_second',
        generation: 8,
      );
      await emit({
        'role': role,
        'content': 'Synthetic old event',
        'identity': oldScope,
      });
      expect(received, isEmpty);
      await emit({
        'role': role,
        'content': 'Synthetic current event',
        'identity': identity(),
      });
      expect(received, ['$role:Synthetic current event']);
    });
  }

  for (final field in [
    'origin',
    'owner',
    'session_id',
    'session_key',
    'native_generation',
    'signed_in',
  ]) {
    test('a mismatched $field cannot enter the current conversation', () async {
      final received = <String>[];
      await start(received);
      final scope = identity();
      scope[field] = switch (field) {
        'native_generation' => 6,
        'signed_in' => false,
        _ => 'different-synthetic-value',
      };
      await emit({
        'role': 'assistant',
        'content': 'Synthetic old event',
        'identity': scope,
      });
      expect(received, isEmpty);
    });
  }

  test(
    'identity-less, malformed and unsupported-role events fail closed',
    () async {
      final received = <String>[];
      await start(received);
      await emit({'role': 'assistant', 'content': 'Synthetic legacy event'});
      await emit({
        'role': 'assistant',
        'content': 'Synthetic malformed event',
        'identity': {...identity(), 'native_generation': '7'},
      });
      await emit({
        'role': 'error',
        'content': 'Synthetic unsupported event',
        'identity': identity(),
      });
      expect(received, isEmpty);
    },
  );

  test(
    'native generation replacement rejects an otherwise identical old event',
    () async {
      final received = <String>[];
      await start(received);
      final oldScope = identity();
      final prefs = await SharedPreferences.getInstance();
      await prefs.setInt('troika_native_identity_revision', 8);
      await emit({
        'role': 'assistant',
        'content': 'Synthetic stale event',
        'identity': oldScope,
      });
      expect(received, isEmpty);
    },
  );

  test(
    'same-identity credential rotation does not discard a valid event',
    () async {
      final received = <String>[];
      await start(received);
      final scope = identity();
      await configure(credential: 'trk_live_synthetic_rotated');
      await emit({
        'role': 'assistant',
        'content': 'Synthetic reply',
        'identity': scope,
      });
      expect(received, ['assistant:Synthetic reply']);
    },
  );

  test(
    'native preferences are reloaded before accepting a new native generation',
    () async {
      final received = <String>[];
      await start(received);
      final scope = {...identity(), 'native_generation': 8};
      // Simulate a native write while Flutter still holds its previous cached prefs.
      SharedPreferences.setMockInitialValues({
        'troika_server_url': 'https://voice.example.test',
        'troika_account_email': 'first@example.test',
        'troika_api_key': 'trk_live_synthetic_first',
        'troika_session_id': 'ses_first',
        'troika_session_key': 'ses_first',
        'troika_native_identity_revision': 8,
        'troika_hosted_endpoint_migration_version': 2,
      });
      expect(TroikaConfig.nativeIdentityRevision, 7);
      await emit({
        'role': 'assistant',
        'content': 'Synthetic current event',
        'identity': scope,
      });
      expect(TroikaConfig.nativeIdentityRevision, 8);
      expect(received, ['assistant:Synthetic current event']);
    },
  );

  for (final mode in ['local', 'manual gateway']) {
    test('$mode events remain available without an account', () async {
      await configure(
        origin: mode == 'local' ? '' : 'https://gateway.example.test',
        owner: '',
        credential: mode == 'local' ? '' : 'synthetic_manual_key',
        session: 'local_session',
      );
      final received = <String>[];
      await start(received);
      final oldScope = identity();
      await emit({
        'role': 'assistant',
        'content': 'Synthetic local result',
        'identity': oldScope,
      });
      expect(received, ['assistant:Synthetic local result']);
      await configure(generation: 8);
      await emit({
        'role': 'assistant',
        'content': 'Synthetic stale local result',
        'identity': oldScope,
      });
      expect(received, ['assistant:Synthetic local result']);
    });
  }

  for (final restart in [false, true]) {
    test(
      'Stop${restart ? ' and restart' : ''} discards an event awaiting identity reload',
      () async {
        final received = <String>[];
        final entered = Completer<void>(), release = Completer<void>();
        final service = await start(
          received,
          reload: () async {
            entered.complete();
            await release.future;
            await TroikaConfig.reloadAccountSession();
          },
        );
        final pending = emit({
          'role': 'assistant',
          'content': 'Synthetic delayed event',
          'identity': identity(),
        });
        await entered.future.timeout(const Duration(seconds: 2));
        await service.stopListening();
        if (restart) await service.startListening();
        release.complete();
        await pending;
        expect(received, isEmpty);
      },
    );
  }
}
