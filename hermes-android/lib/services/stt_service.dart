import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
import '../config/troika_config.dart';
import 'troika_api_service.dart';

/// STT через Troika PC прокси-сервер (порт 8643).
/// Аудио отправляется на PC, там Groq Whisper делает распознавание.
class SttService {
  static const Duration _timeout = Duration(seconds: 30);

  Future<String> transcribe(File audioFile) async {
    final uri = TroikaConfig.transcriptionUri;

    try {
      final request = http.MultipartRequest('POST', uri)
        ..headers['Authorization'] = 'Bearer ${TroikaConfig.apiKey}'
        ..headers['X-Hermes-Session-Id'] = TroikaConfig.sessionId
        ..fields['language'] = 'ru'
        ..files.add(await http.MultipartFile.fromPath(
          'file',
          audioFile.path,
          // Имя с реальным расширением (wav на десктопе, m4a на мобилке) —
          // Groq Whisper определяет формат по расширению файла.
          filename: 'voice.${audioFile.path.split('.').last}',
        ));

      final streamed = await request.send().timeout(_timeout);
      final response =
          await http.Response.fromStream(streamed).timeout(_timeout);

      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        return (data['text'] as String?)?.trim() ?? '';
      }

      throw TroikaApiException(
          'Распознавание речи недоступно (${response.statusCode}).');
    } on SocketException {
      throw TroikaApiException(
          'Нет связи с сервером распознавания речи. Проверь подключение.');
    } on TimeoutException {
      throw TroikaApiException('STT не отвечает.');
    }
  }
}
