import 'dart:convert';
import 'dart:io';
import 'package:crypto/crypto.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import 'package:open_filex/open_filex.dart';
import '../config/troika_config.dart';

/// Один личный документ, созданный Тройкой для текущего аккаунта.
class TroikaFile {
  final String id;
  final String name;
  final int size;
  final double created; // unix-время
  final String ext;
  final String mimeType;
  final String? localPath;

  TroikaFile({
    required this.id,
    required this.name,
    required this.size,
    required this.created,
    required this.ext,
    required this.mimeType,
    this.localPath,
  });

  factory TroikaFile.fromJson(Map<String, dynamic> j) => TroikaFile(
        id: (j['id'] ?? '').toString(),
        name: (j['filename'] ?? '').toString(),
        size: (j['size'] as num?)?.toInt() ?? 0,
        created: (j['created_at'] as num?)?.toDouble() ?? 0,
        ext: (j['kind'] ?? '').toString(),
        mimeType: (j['mime_type'] ?? 'application/octet-stream').toString(),
        localPath: j['local_path'] as String?,
      );

  DateTime get time =>
      DateTime.fromMillisecondsSinceEpoch((created * 1000).round());
}

class FileSaveResult {
  final bool saved;
  final String? error;

  const FileSaveResult._({required this.saved, this.error});

  const FileSaveResult.saved() : this._(saved: true);
  const FileSaveResult.cancelled() : this._(saved: false);
  const FileSaveResult.failed(String message)
      : this._(saved: false, error: message);
}

/// Доступ только к личным документам аутентифицированного пользователя.
class FilesService {
  final http.Client? _client;
  final Future<Directory> Function()? _documentsDirectory;
  FilesService(
      {http.Client? client, Future<Directory> Function()? documentsDirectory})
      : _client = client,
        _documentsDirectory = documentsDirectory;

  Future<http.Response> _get(Uri uri) => _client != null
      ? _client.get(uri, headers: TroikaConfig.headers)
      : http.get(uri, headers: TroikaConfig.headers);
  Future<http.Response> _ack(Uri uri) => _client != null
      ? _client.post(uri, headers: TroikaConfig.headers)
      : http.post(uri, headers: TroikaConfig.headers);
  static const Duration _timeout = Duration(seconds: 20);
  static const MethodChannel _platform =
      MethodChannel('com.troika.hermes/background');

  Future<Directory> localRoot() async {
    final dir = await (_documentsDirectory?.call() ??
        getApplicationDocumentsDirectory());
    final owner = sha256
        .convert(utf8.encode(TroikaConfig.accountEmail.isEmpty
            ? TroikaConfig.sessionId
            : TroikaConfig.accountEmail.toLowerCase()))
        .toString();
    final root = Directory('${dir.path}/troika_files/$owner');
    await root.create(recursive: true);
    return root;
  }

  Future<List<TroikaFile>> localFiles() async {
    final root = await localRoot();
    final files = <TroikaFile>[];
    await for (final item in root.list(followLinks: false)) {
      if (item is! File || !item.path.endsWith('.metadata.json')) continue;
      try {
        final value =
            json.decode(await item.readAsString()) as Map<String, dynamic>;
        final file = TroikaFile.fromJson(value);
        // Never trust a persisted path outside this account's app directory.
        if (validLocalIdentity(file.id, file.ext) &&
            file.localPath == '${root.path}/${file.id}.${file.ext}' &&
            await FileSystemEntity.type(file.localPath!, followLinks: false) ==
                FileSystemEntityType.file &&
            await File(file.localPath!).exists()) {
          files.add(file);
        }
      } catch (_) {/* Ignore incomplete or malformed metadata. */}
    }
    files.sort((a, b) => b.created.compareTo(a.created));
    return files;
  }

  /// Save bytes first, then metadata, and only then acknowledge the RAM handoff.
  Future<TroikaFile> receiveDeviceFile(Map<String, dynamic> artifact) async {
    final id = (artifact['id'] ?? '').toString();
    final kind = (artifact['kind'] ?? '').toString();
    if (!validLocalIdentity(id, kind)) {
      throw const FormatException('Некорректный файл от Тройки.');
    }
    final root = await localRoot();
    final target = File('${root.path}/$id.$kind');
    final uri = Uri.parse('${TroikaConfig.serverUrl}/v1/device-files/$id');
    // Lost acknowledgements may leave a delivery pending although its local copy is complete.
    final existing = File('${target.path}.metadata.json');
    if (await existing.exists() &&
        await FileSystemEntity.type(target.path, followLinks: false) ==
            FileSystemEntityType.file) {
      final bytes = await target.readAsBytes();
      if (sha256.convert(bytes).toString() == artifact['sha256']) {
        try {
          await _ack(Uri.parse('$uri/received')).timeout(_timeout);
        } catch (_) {}
        return TroikaFile.fromJson(
            json.decode(await existing.readAsString()) as Map<String, dynamic>);
      }
    }
    final response = await _get(uri).timeout(const Duration(seconds: 60));
    if (response.statusCode != 200) {
      throw const HttpException(
          'Не удалось получить файл. Попроси Тройку создать его заново.');
    }
    validateDeviceBytes(
        response.bodyBytes, kind, (artifact['size'] as num?)?.toInt() ?? 0);
    if (artifact['sha256'] != sha256.convert(response.bodyBytes).toString()) {
      throw const FormatException('Контрольная сумма файла не совпадает.');
    }
    final partial = File('${target.path}.partial');
    await partial.writeAsBytes(response.bodyBytes, flush: true);
    await partial.rename(target.path);
    final metadata = {...artifact, 'local_path': target.path};
    final metaFile = File('${target.path}.metadata.json');
    final metaPartial = File('${metaFile.path}.partial');
    await metaPartial.writeAsString(json.encode(metadata), flush: true);
    await metaPartial.rename(metaFile.path);
    // A lost acknowledgement does not undo a successful local save. TTL cleans it up.
    try {
      await _ack(Uri.parse('$uri/received')).timeout(_timeout);
    } catch (_) {}
    return TroikaFile.fromJson(metadata);
  }

  static void validateDeviceBytes(
      Uint8List bytes, String kind, int expectedSize) {
    final signature = kind == 'pdf' ? [37, 80, 68, 70, 45] : [80, 75, 3, 4];
    if (bytes.length != expectedSize ||
        bytes.isEmpty ||
        bytes.length > 50 * 1024 * 1024 ||
        bytes.length < signature.length ||
        !List.generate(signature.length, (i) => bytes[i] == signature[i])
            .every((v) => v)) {
      throw const FormatException('Файл повреждён или не завершён.');
    }
  }

  static bool validLocalIdentity(String id, String kind) =>
      RegExp(r'^delivery_[0-9a-f]{32}$').hasMatch(id) &&
      {'docx', 'pdf', 'pptx', 'zip'}.contains(kind);

  /// Recover deliveries missed when the app disconnected from a run's event stream.
  Future<void> recoverPending() async {
    final response =
        await _get(Uri.parse('${TroikaConfig.serverUrl}/v1/device-files'))
            .timeout(_timeout);
    if (response.statusCode != 200) return;
    final body =
        json.decode(utf8.decode(response.bodyBytes)) as Map<String, dynamic>;
    for (final artifact
        in (body['data'] as List? ?? []).whereType<Map<String, dynamic>>()) {
      await receiveDeviceFile(artifact);
    }
  }

  Future<List<TroikaFile>> list() async {
    try {
      await recoverPending();
    } catch (_) {/* Local files remain available offline. */}
    final local = await localFiles();
    try {
      final uri = Uri.parse(TroikaConfig.artifactsUrl);
      final resp = await _get(uri).timeout(_timeout);
      if (resp.statusCode == 404) return local;
      if (resp.statusCode != 200) {
        throw Exception('Не удалось получить файлы (${resp.statusCode}).');
      }
      final data =
          json.decode(utf8.decode(resp.bodyBytes)) as Map<String, dynamic>;
      final raw = (data['data'] as List?) ?? const [];
      return [
        ...local,
        ...raw
            .whereType<Map<String, dynamic>>()
            .map(TroikaFile.fromJson)
            .toList()
      ];
    } on SocketException {
      if (local.isNotEmpty) return local;
      rethrow;
    } catch (_) {
      if (local.isNotEmpty) return local;
      rethrow;
    }
  }

  Future<File> _download(TroikaFile file) async {
    if (file.localPath != null) {
      final root = await localRoot();
      if (!validLocalIdentity(file.id, file.ext) ||
          file.localPath != '${root.path}/${file.id}.${file.ext}' ||
          await FileSystemEntity.type(file.localPath!, followLinks: false) !=
              FileSystemEntityType.file) {
        throw const FormatException('Файл относится к другому аккаунту.');
      }
      return File(file.localPath!);
    }
    if (!RegExp(r'^art_[0-9a-f]{32}$').hasMatch(file.id)) {
      throw const FormatException('Некорректный идентификатор файла.');
    }
    final uri = Uri.parse('${TroikaConfig.artifactsUrl}/${file.id}/download');
    final resp = await _get(uri).timeout(const Duration(seconds: 60));
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

  /// Save a durable copy through the platform document picker.
  ///
  /// On Android/iOS file_picker writes [bytes] to the user-selected location.
  /// Desktop pickers return a path, so the copy is written here after choice.
  Future<FileSaveResult> saveToDevice(TroikaFile file) async {
    try {
      final downloaded = await _download(file);
      final bytes = await downloaded.readAsBytes();
      final isMobile = Platform.isAndroid || Platform.isIOS;
      final target = await FilePicker.platform.saveFile(
        dialogTitle: 'Сохранить файл на устройство',
        fileName: file.name,
        type: FileType.custom,
        allowedExtensions: [file.ext],
        bytes: isMobile ? bytes : null,
      );
      if (target == null) return const FileSaveResult.cancelled();
      if (!isMobile) {
        await File(target).writeAsBytes(bytes, flush: true);
      }
      return const FileSaveResult.saved();
    } on SocketException {
      return const FileSaveResult.failed('Нет соединения с сервером.');
    } catch (e) {
      return FileSaveResult.failed('Ошибка сохранения: $e');
    }
  }

  Future<String?> deleteFile(TroikaFile file) async {
    try {
      if (file.localPath != null) {
        final local = await _download(file);
        await local.delete();
        final meta = File('${local.path}.metadata.json');
        if (await meta.exists()) await meta.delete();
        return null;
      }
      if (!RegExp(r'^art_[0-9a-f]{32}$').hasMatch(file.id)) {
        return 'Некорректный идентификатор файла.';
      }
      final uri = Uri.parse('${TroikaConfig.artifactsUrl}/${file.id}');
      final response = await http
          .delete(uri, headers: TroikaConfig.headers)
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
