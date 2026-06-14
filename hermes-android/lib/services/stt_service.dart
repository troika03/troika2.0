import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
import '../config/hermes_config.dart';
import 'hermes_api_service.dart';

/// STT через Hermes PC прокси-сервер (порт 8643)
/// Аудио отправляется на PC, там Groq Whisper делает распознавание.
class SttService {
  static const Duration _timeout = Duration(seconds: 30);

  Future<String> transcribe(File audioFile) async {
    // STT прокси работает на порту 8643 (рядом с Hermes 8642)
    final baseUrl = HermesConfig.serverUrl.replaceFirst(
      RegExp(r':\d+$'),
      ':8643',
    );
    final uri = Uri.parse('$baseUrl/v1/audio/transcriptions');

    try {
      final request = http.MultipartRequest('POST', uri)
        ..headers['Authorization'] = 'Bearer ${HermesConfig.apiKey}'
        ..fields['language'] = 'ru'
        ..files.add(await http.MultipartFile.fromPath(
          'file',
          audioFile.path,
          filename: 'voice.m4a',
        ));

      final streamed = await request.send().timeout(_timeout);
      final response = await http.Response.fromStream(streamed);

      if (response.statusCode == 200) {
        final data = json.decode(response.body);
        return (data['text'] as String?)?.trim() ?? '';
      }

      throw HermesApiException(
          'STT ошибка ${response.statusCode}: ${response.body}');
    } on SocketException {
      throw HermesApiException(
          'Нет связи с STT сервером.\nЗапусти на PC: python stt_proxy_server.py');
    } on TimeoutException {
      throw HermesApiException('STT не отвечает.');
    }
  }
}
