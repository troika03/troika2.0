import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:troika_assistant/config/troika_config.dart';
import 'package:troika_assistant/services/progressive_speech_player.dart';
import 'package:troika_assistant/services/ram_mp3_http_adapter.dart';
import 'package:troika_assistant/services/ram_mp3_source.dart';
import 'package:troika_assistant/services/tts_service.dart';

class _RealHttpOverrides extends HttpOverrides {
  @override
  HttpClient createHttpClient(SecurityContext? context) =>
      super.createHttpClient(context)..findProxy = (_) => 'DIRECT';
}

/// Only the native player is replaced. It reads the real owned HTTP endpoint.
class _Player implements ProgressiveSpeechPlayer {
  _Player({
    this.loadGate,
    this.emitCompleted = true,
    this.returnPlayEarly = false,
  });
  final Future<void>? loadGate;
  final bool emitCompleted, returnPlayEarly;
  final loaded = Completer<Uri>(), firstBytes = Completer<void>();
  final states = StreamController<bool>.broadcast(sync: true);
  final failureEvents = StreamController<Object>.broadcast(sync: true);
  final ended = Completer<void>();
  HttpClient? client;
  Uri? uri;
  int playCalls = 0, stopCalls = 0;
  bool disposed = false, stopped = false, eof = false;
  Object? cleanupFailure;
  @override
  Stream<bool> get completed => states.stream;
  @override
  Stream<Object> get failures => failureEvents.stream;
  @override
  Future<void> setSource(Uri value) async {
    expect(value.host, InternetAddress.loopbackIPv4.address);
    uri = value;
    loaded.complete(value);
    if (loadGate != null) await loadGate;
  }

  @override
  Future<void> play() {
    playCalls++;
    unawaited(_read());
    return returnPlayEarly ? Future<void>.value() : ended.future;
  }

  Future<void> _read() async {
    try {
      client = HttpClient();
      final response = await (await client!.getUrl(uri!)).close();
      expect(response.statusCode, 200);
      expect(response.headers.value('transfer-encoding'), 'chunked');
      expect(response.headers.value('cache-control'), 'no-store');
      await for (final chunk in response) {
        if (chunk.isNotEmpty && !firstBytes.isCompleted) firstBytes.complete();
      }
      eof = true;
      if (emitCompleted && !stopped && !disposed) states.add(true);
    } catch (error, stack) {
      if (!stopped && !disposed) states.addError(error, stack);
    } finally {
      client?.close(force: true);
      if (!ended.isCompleted) ended.complete();
    }
  }

  @override
  Future<void> stop() async {
    stopCalls++;
    stopped = true;
    client?.close(force: true);
    if (!ended.isCompleted) ended.complete();
    if (cleanupFailure != null) throw cleanupFailure!;
  }

  @override
  Future<void> dispose() async {
    disposed = true;
    await stop();
    await states.close();
    await failureEvents.close();
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  final originalHttp = HttpOverrides.current;
  HttpOverrides.global = _RealHttpOverrides();
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  const channel = MethodChannel('com.troika.hermes/background');
  setUp(() async {
    SharedPreferences.setMockInitialValues({
      'troika_server_url': 'https://voice.example.invalid',
      'troika_account_email': 'synthetic@example.invalid',
      'troika_api_key': 'trk_live_synthetic',
      'troika_access_token_expires_at': DateTime.now()
          .add(const Duration(days: 1))
          .millisecondsSinceEpoch,
      'troika_session_id': 'ses_synthetic',
      'troika_session_key': 'ses_synthetic',
    });
    messenger.setMockMethodCallHandler(channel, (call) async {
      if (call.method == 'getRefreshToken') return 'trk_refresh_synthetic';
      return true;
    });
    messenger.setMockMethodCallHandler(
      const MethodChannel('flutter_tts'),
      (_) async => 1,
    );
    await TroikaConfig.init();
  });
  tearDown(() {
    messenger.setMockMethodCallHandler(channel, null);
    messenger.setMockMethodCallHandler(
      const MethodChannel('flutter_tts'),
      null,
    );
  });
  tearDownAll(() {
    HttpOverrides.global = originalHttp;
  });

  Future<void> withAudio(
    Stream<List<int>> audio,
    Future<void> Function(List<Map<String, dynamic>>) body, {
    int status = 200,
    String contentType = 'audio/mpeg; charset=binary',
  }) async {
    final requests = <Map<String, dynamic>>[];
    await http.runWithClient(
      () => body(requests),
      () => MockClient.streaming((request, bytes) async {
        expect(
          request.url.toString(),
          'https://voice.example.invalid/v1/audio/speech',
        );
        expect(request.followRedirects, isFalse);
        final input =
            jsonDecode(await bytes.bytesToString()) as Map<String, dynamic>;
        requests.add(input);
        return http.StreamedResponse(
          audio,
          status,
          headers: {'content-type': contentType},
        );
      }),
    );
  }

  test(
    'progressive POST opts into streaming; real RAM HTTP yields bytes before EOF',
    () async {
      final upstream = StreamController<List<int>>(sync: true);
      final player = _Player();
      LiveMp3Source? source;
      final service = TtsService(
        progressive: true,
        playerFactory: () => player,
        bindAdapter: (value, deadline) async {
          source = value;
          expect(deadline, const Duration(seconds: 90));
          return RamMp3HttpAdapter.bind(value, readerDeadline: deadline);
        },
      );
      try {
        await withAudio(upstream.stream, (requests) async {
          final reply = service.beginReply();
          reply.add('Синтетическая фраза!');
          var finished = false;
          final finish = reply.finish().then((_) => finished = true);
          await player.loaded.future.timeout(const Duration(seconds: 2));
          upstream.add(List.filled(32768, 7));
          await player.firstBytes.future.timeout(const Duration(seconds: 2));
          expect(player.eof, isFalse);
          expect(finished, isFalse);
          expect(requests.single['stream'], isTrue);
          expect(requests.single['response_format'], 'mp3');
          upstream.add([1, 2, 3]);
          await upstream.close();
          await finish.timeout(const Duration(seconds: 2));
          expect(player.eof, isTrue);
          expect(player.disposed, isTrue);
          expect(source!.bufferedBytes, 0);
          expect(source!.activeReaders, 0);
          expect(service.isSpeaking, isFalse);
        });
      } finally {
        await service.stop();
        service.dispose();
      }
    },
  );

  test(
    'Stop invalidates source immediately while owned bind is pending',
    () async {
      final upstream = StreamController<List<int>>(sync: true);
      final bound = Completer<RamMp3HttpAdapter>(), release = Completer<void>();
      final player = _Player();
      LiveMp3Source? source;
      final service = TtsService(
        progressive: true,
        playerFactory: () => player,
        bindAdapter: (value, deadline) async {
          source = value;
          final adapter = await RamMp3HttpAdapter.bind(
            value,
            readerDeadline: deadline,
          );
          bound.complete(adapter);
          await release.future;
          return adapter;
        },
      );
      try {
        await withAudio(upstream.stream, (_) async {
          final reply = service.beginReply();
          reply.add('Синтетическая фраза!');
          final finish = reply.finish();
          final adapter = await bound.future.timeout(
            const Duration(seconds: 2),
          );
          final uri = adapter.uri;
          upstream.add([1, 2, 3]);
          await service.stop();
          expect(reply.isCurrent, isFalse);
          expect(source!.bufferedBytes, 0);
          release.complete();
          await finish;
          await Future<void>.delayed(const Duration(milliseconds: 30));
          expect(player.playCalls, 0);
          final client = HttpClient();
          try {
            await expectLater(
              client.getUrl(uri),
              throwsA(isA<SocketException>()),
            );
          } finally {
            client.close(force: true);
          }
        });
      } finally {
        if (!release.isCompleted) release.complete();
        await service.stop();
        service.dispose();
        await upstream.close();
      }
    },
  );

  test(
    'Stop during setSource never calls play after late load completion',
    () async {
      final gate = Completer<void>();
      final player = _Player(loadGate: gate.future);
      final service = TtsService(
        progressive: true,
        playerFactory: () => player,
      );
      try {
        await withAudio(Stream.value([1, 2, 3]), (_) async {
          final reply = service.beginReply();
          reply.add('Синтетическая фраза!');
          final finish = reply.finish();
          await player.loaded.future.timeout(const Duration(seconds: 2));
          await service.stop();
          gate.complete();
          await finish;
          await Future<void>.delayed(Duration.zero);
          expect(player.playCalls, 0);
          expect(player.disposed, isTrue);
        });
      } finally {
        if (!gate.isCompleted) gate.complete();
        await service.stop();
        service.dispose();
      }
    },
  );

  for (final transition in [
    'logout',
    'revoke',
    'delete',
    'owner',
    'session',
    'endpoint',
    'credential',
    'dispose',
  ]) {
    test(
      '$transition invalidates a loaded source before native play',
      () async {
        final gate = Completer<void>();
        final player = _Player(loadGate: gate.future);
        final service = TtsService(
          progressive: true,
          playerFactory: () => player,
        );
        try {
          await withAudio(Stream.value([1, 2, 3]), (_) async {
            final reply = service.beginReply();
            reply.add('Синтетическая фраза!');
            final finish = reply.finish();
            await player.loaded.future.timeout(const Duration(seconds: 2));
            switch (transition) {
              case 'logout':
                final pending = TroikaConfig.signOut();
                expect(reply.isCurrent, isFalse);
                await pending;
              case 'revoke':
                await TroikaConfig.clearRevokedDevice();
              case 'delete':
                await TroikaConfig.clearDeletedAccount();
              case 'owner':
                await TroikaConfig.saveAccount(
                  email: 'other@example.invalid',
                  token: 'trk_live_other',
                  homeSessionId: 'ses_other',
                );
              case 'session':
                await TroikaConfig.saveAccount(
                  email: TroikaConfig.accountEmail,
                  token: TroikaConfig.apiKey,
                  homeSessionId: 'ses_other',
                );
              case 'endpoint':
                TroikaConfig.serverUrl = 'https://other.example.invalid';
              case 'credential':
                TroikaConfig.apiKey = 'trk_live_settings_replacement';
              case 'dispose':
                service.dispose();
            }
            expect(reply.isCurrent, isFalse);
            gate.complete();
            await finish;
            await Future<void>.delayed(Duration.zero);
            expect(player.playCalls, 0);
          });
        } finally {
          if (!gate.isCompleted) gate.complete();
          await service.stop();
          service.dispose();
        }
      },
    );
  }

  test(
    'same-owner token refresh preserves the current voice identity',
    () async {
      final service = TtsService(progressive: true);
      try {
        final reply = service.beginReply();
        final revision = TroikaConfig.voiceIdentityRevision;
        await TroikaConfig.saveAccount(
          email: TroikaConfig.accountEmail,
          token: 'trk_live_rotated',
          homeSessionId: TroikaConfig.sessionId,
          accessExpiresAt: DateTime.now().millisecondsSinceEpoch / 1000 + 86400,
        );
        expect(TroikaConfig.voiceIdentityRevision, revision);
        expect(reply.isCurrent, isTrue);
      } finally {
        await service.stop();
        service.dispose();
      }
    },
  );

  test('empty EOF fails promptly without a native completion event', () async {
    final player = _Player(emitCompleted: false, returnPlayEarly: true);
    final service = TtsService(progressive: true, playerFactory: () => player);
    try {
      await withAudio(const Stream.empty(), (_) async {
        final reply = service.beginReply();
        reply.add('Синтетическая фраза!');
        await expectLater(
          reply.finish().timeout(const Duration(seconds: 1)),
          throwsA(isA<StateError>()),
        );
        expect(player.disposed, isTrue);
      });
    } finally {
      await service.stop();
      service.dispose();
    }
  });

  test(
    'native failure fails promptly even when play future succeeds',
    () async {
      final player = _Player(emitCompleted: false, returnPlayEarly: true);
      final service = TtsService(
        progressive: true,
        playerFactory: () => player,
      );
      try {
        await withAudio(
          Stream<List<int>>.multi((sink) {
            sink.add(List.filled(32768, 7));
            sink.close();
          }),
          (_) async {
            final reply = service.beginReply();
            reply.add('Синтетическая фраза!');
            final error = StateError('Synthetic native decoder failure');
            final check = expectLater(
              reply.finish().timeout(const Duration(seconds: 1)),
              throwsA(same(error)),
            );
            await player.firstBytes.future.timeout(const Duration(seconds: 1));
            player.failureEvents.add(error);
            await check;
            expect(player.disposed, isTrue);
          },
        );
      } finally {
        await service.stop();
        service.dispose();
      }
    },
  );

  for (final contentType in ['text/html', 'application/json', '']) {
    test('rejects unvalidated MIME $contentType before RAM bind', () async {
      var binds = 0;
      final service = TtsService(
        progressive: true,
        bindAdapter: (source, deadline) async {
          binds++;
          return RamMp3HttpAdapter.bind(source, readerDeadline: deadline);
        },
      );
      try {
        await withAudio(const Stream.empty(), (_) async {
          final reply = service.beginReply()..add('Синтетическая фраза!');
          await expectLater(reply.finish(), throwsA(isA<StateError>()));
          expect(binds, 0);
        }, contentType: contentType);
      } finally {
        await service.stop();
        service.dispose();
      }
    });
  }

  test('native failure interrupts a still-pending source load', () async {
    final gate = Completer<void>();
    final player = _Player(loadGate: gate.future);
    final service = TtsService(progressive: true, playerFactory: () => player);
    try {
      await withAudio(Stream.value([1, 2, 3]), (_) async {
        final reply = service.beginReply()..add('Синтетическая фраза!');
        final error = StateError('Synthetic native load failure');
        final check = expectLater(
          reply.finish().timeout(const Duration(seconds: 1)),
          throwsA(same(error)),
        );
        await player.loaded.future.timeout(const Duration(seconds: 1));
        player.failureEvents.add(error);
        await check;
        expect(player.playCalls, 0);
        expect(player.disposed, isTrue);
      });
    } finally {
      if (!gate.isCompleted) gate.complete();
      await service.stop();
      service.dispose();
    }
  });

  test('empty EOF interrupts a still-pending source load', () async {
    final gate = Completer<void>();
    final player = _Player(loadGate: gate.future);
    final service = TtsService(progressive: true, playerFactory: () => player);
    try {
      await withAudio(const Stream.empty(), (_) async {
        final reply = service.beginReply()..add('Синтетическая фраза!');
        await expectLater(
          reply.finish().timeout(const Duration(seconds: 1)),
          throwsA(isA<StateError>()),
        );
        expect(player.playCalls, 0);
        expect(player.disposed, isTrue);
      });
    } finally {
      if (!gate.isCompleted) gate.complete();
      await service.stop();
      service.dispose();
    }
  });

  test('late speak preflight cannot replace a newer reply', () async {
    final stopRequested = Completer<void>(), releaseStop = Completer<void>();
    messenger.setMockMethodCallHandler(const MethodChannel('flutter_tts'), (
      call,
    ) async {
      if (call.method == 'stop' && !stopRequested.isCompleted) {
        stopRequested.complete();
        await releaseStop.future;
      }
      return 1;
    });
    final service = TtsService(progressive: true);
    try {
      await withAudio(const Stream.empty(), (requests) async {
        final old = service
            .speak('Старая синтетическая фраза!')
            .catchError((Object _) {});
        await stopRequested.future.timeout(const Duration(seconds: 1));
        final current = service.beginReply();
        releaseStop.complete();
        await old;
        expect(current.isCurrent, isTrue);
        expect(requests, isEmpty);
      }, status: 503);
    } finally {
      if (!releaseStop.isCompleted) releaseStop.complete();
      await service.stop();
      service.dispose();
    }
  });

  test(
    'replacement observes failing predecessor cleanup without new deltas',
    () async {
      final input = StreamController<List<int>>();
      final player = _Player();
      final service = TtsService(
        progressive: true,
        playerFactory: () => player,
      );
      try {
        await withAudio(input.stream, (_) async {
          service.beginReply().add('Синтетическая фраза!');
          await player.loaded.future.timeout(const Duration(seconds: 1));
          input.add(List.filled(32768, 7));
          await player.firstBytes.future.timeout(const Duration(seconds: 1));
          player.cleanupFailure = StateError('Synthetic cleanup failure');
          final next = service.beginReply();
          await Future<void>.delayed(const Duration(milliseconds: 50));
          expect(next.isCurrent, isTrue);
          expect(player.stopCalls, greaterThan(0));
        });
      } finally {
        player.cleanupFailure = null;
        await service.stop();
        service.dispose();
        await player.dispose();
        await input.close();
      }
    },
  );

  test(
    'desktop request retains buffered server contract without stream flag',
    () async {
      final service = TtsService(progressive: false);
      try {
        await withAudio(const Stream.empty(), (requests) async {
          final reply = service.beginReply()..add('Синтетическая фраза!');
          await expectLater(reply.finish(), throwsA(isA<StateError>()));
          expect(requests.single.containsKey('stream'), isFalse);
        }, status: 503);
      } finally {
        await service.stop();
        service.dispose();
      }
    },
  );

  test(
    'late source load from previous reply never starts or clears new reply',
    () async {
      final gate = Completer<void>();
      final oldPlayer = _Player(loadGate: gate.future), newPlayer = _Player();
      var players = 0;
      final service = TtsService(
        progressive: true,
        playerFactory: () => ++players == 1 ? oldPlayer : newPlayer,
      );
      try {
        await withAudio(
          Stream<List<int>>.multi((sink) {
            sink.add(List.filled(32768, 7));
            sink.close();
          }),
          (_) async {
            final oldReply = service.beginReply()..add('Старая фраза!');
            final oldFinished = oldReply.finish();
            await oldPlayer.loaded.future.timeout(const Duration(seconds: 2));
            final newReply = service.beginReply()..add('Новая фраза!');
            expect(oldReply.isCurrent, isFalse);
            expect(newReply.isCurrent, isTrue);
            oldReply.add('Поздняя старая фраза!');
            await oldFinished;
            gate.complete();
            await newReply.finish().timeout(const Duration(seconds: 2));
            expect(oldPlayer.playCalls, 0);
            expect(oldPlayer.disposed, isTrue);
            expect(newPlayer.playCalls, 1);
            expect(newPlayer.disposed, isTrue);
            expect(players, 2);
          },
        );
      } finally {
        if (!gate.isCompleted) gate.complete();
        await service.stop();
        service.dispose();
      }
    },
  );

  test(
    'play future and upstream EOF cannot replace a completion event',
    () async {
      final player = _Player(emitCompleted: false, returnPlayEarly: true);
      final service = TtsService(
        progressive: true,
        playerFactory: () => player,
        playbackDeadline: const Duration(milliseconds: 150),
      );
      try {
        await withAudio(Stream.value(List.filled(32768, 7)), (_) async {
          final reply = service.beginReply();
          reply.add('Синтетическая фраза!');
          await expectLater(reply.finish(), throwsA(isA<TimeoutException>()));
          expect(player.playCalls, 1);
          expect(player.disposed, isTrue);
        });
      } finally {
        await service.stop();
        service.dispose();
      }
    },
  );
}
