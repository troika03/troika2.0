import 'dart:convert';
import 'dart:io';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import 'package:open_filex/open_filex.dart';
import '../config/hermes_config.dart';

/// Один личный документ, созданный Тройкой для текущего аккаунта.
class TroikaFile {
  final String id;
  final String name;
  final int size;
  final double created; // unix-время
  final String ext;
  final String mimeType;

  TroikaFile({
    required this.id,
    required this.name,
    required this.size,
    required this.created,
    required this.ext,
    required this.mimeType,
  });

  factory TroikaFile.fromJson(Map<String, dynamic> j) => TroikaFile(
        id: (j['id'] ?? '').toString(),
        name: (j['filename'] ?? '').toString(),
        size: (j['size'] as num?)?.toInt() ?? 0,
        created: (j['created_at'] as num?)?.toDouble() ?? 0,
        ext: (j['kind'] ?? '').toString(),
        mimeType: (j['mime_type'] ?? 'application/octet-stream').toString(),
      );

  DateTime get time =>
      DateTime.fromMillisecondsSinceEpoch((created * 1000).round());
}

/// Доступ только к личным документам аутентифицированного пользователя.
class FilesService {
  static const Duration _timeout = Duration(seconds: 20);
  static const MethodChannel _platform =
      MethodChannel('com.troika.hermes/background');

  Future<List<TroikaFile>> list() async {
    final uri = Uri.parse(HermesConfig.artifactsUrl);
    final resp =
        await http.get(uri, headers: HermesConfig.headers).timeout(_timeout);
    if (resp.statusCode == 404) return [];
    if (resp.statusCode != 200) {
      throw Exception('Не удалось получить файлы (${resp.statusCode}).');
    }
    final data =
        json.decode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
    final raw = (data['data'] as List?) ?? const [];
    return raw
        .whereType<Map<String, dynamic>>()
        .map(TroikaFile.fromJson)
        .toList();
  }

  Future<File> _download(TroikaFile file) async {
    if (!RegExp(r'^art_[0-9a-f]{32}$').hasMatch(file.id)) {
      throw const FormatException('Некорректный идентификатор файла.');
    }
    final uri = Uri.parse('${HermesConfig.artifactsUrl}/${file.id}/download');
    final resp = await http
        .get(uri, headers: HermesConfig.headers)
        .timeout(const Duration(seconds: 60));
    if (resp.statusCode != 200) {
      throw HttpException('Не удалось скачать файл (${resp.statusCode}).');
    }
    final dir = await getTemporaryDirectory();
    final safeName = file.name.replaceAll(RegExp(r'[\\/:*?"<>|]'), '_');
    final target = File('${dir.path}/$safeName');
    await target.writeAsBytes(resp.bodyBytes, flush: true);
    return target;
  }

  Future<String?> openFile(TroikaFile file) async {
    try {
      final downloaded = await _download(file);
      final result = await OpenFilex.open(downloaded.path);
      if (result.type != ResultType.done) {
        return 'Нет приложения для открытия ${file.ext.toUpperCase()}. '
            'Установи Word или Google Документы.';
      }
      return null;
    } on SocketException {
      return 'Нет соединения с сервером.';
    } catch (e) {
      return 'Ошибка открытия: $e';
    }
  }

  Future<String?> shareFile(TroikaFile file) async {
    try {
      final downloaded = await _download(file);
      final shared = await _platform.invokeMethod<bool>('shareFile', {
        'path': downloaded.path,
      });
      return shared == true ? null : 'Не удалось открыть меню «Поделиться».';
    } on PlatformException catch (e) {
      return 'Ошибка отправки: ${e.message ?? e.code}';
    } on SocketException {
      return 'Нет соединения с сервером.';
    } catch (e) {
      return 'Ошибка отправки: $e';
    }
  }

  Future<String?> deleteFile(TroikaFile file) async {
    try {
      if (!RegExp(r'^art_[0-9a-f]{32}$').hasMatch(file.id)) {
        return 'Некорректный идентификатор файла.';
      }
      final uri = Uri.parse('${HermesConfig.artifactsUrl}/${file.id}');
      final response = await http
          .delete(uri, headers: HermesConfig.headers)
          .timeout(_timeout);
      if (response.statusCode == 200) return null;
      if (response.statusCode == 404) return 'Файл уже удалён.';
      return 'Не удалось удалить файл (${response.statusCode}).';
    } on SocketException {
      return 'Нет соединения с сервером.';
    } catch (e) {
      return 'Ошибка удаления: $e';
    }
  }
}
