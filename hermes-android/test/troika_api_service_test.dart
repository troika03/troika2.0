import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:troika_assistant/services/assistant_service.dart';
import 'package:troika_assistant/services/troika_api_service.dart';

void main() {
  test('retryTlsHandshake retries a transient TLS failure', () async {
    var calls = 0;

    final result = await retryTlsHandshake(
      () async {
        calls++;
        if (calls < 4) throw const HandshakeException('transient');
        return 'ok';
      },
      delays: const [Duration.zero, Duration.zero, Duration.zero],
    );

    expect(result, 'ok');
    expect(calls, 4);
  });

  test('retryTlsHandshake rethrows after the retry budget', () async {
    var calls = 0;

    await expectLater(
      retryTlsHandshake(
        () async {
          calls++;
          throw const HandshakeException('persistent');
        },
        delays: const [Duration.zero, Duration.zero, Duration.zero],
      ),
      throwsA(isA<HandshakeException>()),
    );

    expect(calls, 4);
  });

  test('safeErrorMessage hides unexpected implementation details', () {
    expect(
      AssistantService.safeErrorMessage(StateError('secret details')),
      'Не удалось связаться с Тройкой. Повтори попытку.',
    );
    expect(
      AssistantService.safeErrorMessage(
        TroikaApiException('Понятная ошибка.'),
      ),
      'Понятная ошибка.',
    );
  });
}
