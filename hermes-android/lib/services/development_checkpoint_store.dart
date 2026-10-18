import 'dart:collection';
import 'dart:convert';
import 'dart:io';
import 'package:crypto/crypto.dart';
import 'package:flutter/services.dart';
import 'files_service.dart';
import '../config/troika_config.dart';

/// Account-local checkpoints; Android excludes these files from system backup.
class DevelopmentCheckpointStore {
  final FilesService files;
  final Future<Directory> Function()? directory;
  DevelopmentCheckpointStore(this.files, {this.directory});
  static const channel = MethodChannel('troika/development-autopilot');

  static Object? canonical(Object? value) {
    if (value is Map) {
      return SplayTreeMap<String, Object?>.from({
        for (final key in value.keys) key.toString(): canonical(value[key])
      });
    }
    if (value is List) return value.map(canonical).toList();
    return value;
  }

  static String digest(Map<String, dynamic> checkpoint) =>
      sha256.convert(utf8.encode(jsonEncode(canonical(checkpoint)))).toString();

  Future<Directory> _root(String? expectedOwner) async {
    final owner = expectedOwner ?? TroikaConfig.accountEmail;
    if (owner != TroikaConfig.accountEmail)
      throw StateError('Аккаунт изменился.');
    if (directory != null) return directory!();
    final accountRoot = await files.localRoot();
    if (owner != TroikaConfig.accountEmail)
      throw StateError('Аккаунт изменился.');
    final account = accountRoot.path.split(Platform.pathSeparator).last;
    final path = Platform.isAndroid
        ? '${await channel.invokeMethod<String>('storageRoot')}/$account'
        : '${accountRoot.path}/.development';
    final root = Directory(path);
    await root.create(recursive: true);
    return root;
  }

  Future<File> _file(String projectId, String? owner) async {
    if (!RegExp(r'^run_[a-f0-9]{32}$').hasMatch(projectId)) {
      throw const FormatException('Некорректный проект.');
    }
    return File('${(await _root(owner)).path}/$projectId.json');
  }

  Future<Map<String, dynamic>?> read(String projectId, {String? owner}) async {
    final file = await _file(projectId, owner);
    for (final candidate in [file, File('${file.path}.previous')]) {
      if (!await candidate.exists()) continue;
      try {
        if (await candidate.length() > 2600000) continue;
        final value = Map<String, dynamic>.from(
            jsonDecode(await candidate.readAsString()));
        if (value['project_id'] != projectId ||
            value['checkpoint'] is! Map ||
            digest(Map<String, dynamic>.from(value['checkpoint'])) !=
                value['digest']) continue;
        return value;
      } catch (_) {
        /* Retain the last complete copy after an interrupted write. */
      }
    }
    return null;
  }

  Future<void> save(String projectId, Map<String, dynamic> value,
      {String? owner}) async {
    final data = Map<String, dynamic>.from(value['checkpoint'] as Map);
    if (data['version'] != 1 || digest(data) != value['digest']) {
      throw const FormatException('Контрольная копия повреждена.');
    }
    final saved = {...value, 'project_id': projectId}..remove('payload');
    final encoded = utf8.encode(jsonEncode(saved));
    if (encoded.length > 2600000)
      throw const FormatException('Слишком большой проект.');
    final file = await _file(projectId, owner);
    final temporary = File('${file.path}.part');
    final previous = File('${file.path}.previous');
    await temporary.writeAsBytes(encoded, flush: true);
    if (await previous.exists()) await previous.delete();
    if (await file.exists()) await file.rename(previous.path);
    await temporary.rename(file.path);
  }
}
