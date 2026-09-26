import 'dart:async';
import 'dart:io' show File, Platform;
import 'package:flutter/services.dart';

import '../config/troika_config.dart';

typedef WindowsHotkeyHandler = Future<void> Function();

class WindowsShellService {
  WindowsShellService._();

  static const MethodChannel _channel = MethodChannel('troika/windows');
  static WindowsHotkeyHandler? _hotkeyHandler;
  static bool _initialized = false;

  static bool get supported => Platform.isWindows;

  static Future<void> initialize(WindowsHotkeyHandler onHotkey) async {
    if (!supported) return;
    _hotkeyHandler = onHotkey;
    if (!_initialized) {
      _initialized = true;
      _channel.setMethodCallHandler((call) async {
        if (call.method == 'hotkeyPressed') {
          await _hotkeyHandler?.call();
        }
      });
    }
    await registerHotkey(TroikaConfig.windowsHotkey);
  }

  static Future<bool> registerHotkey(String preset) async {
    if (!supported) return false;
    try {
      return await _channel.invokeMethod<bool>('registerHotkey', preset) ??
          false;
    } on MissingPluginException {
      return false;
    } on PlatformException {
      return false;
    }
  }

  static Future<void> showCompact({required bool alwaysOnTop}) async {
    await _invoke('showCompact', alwaysOnTop);
  }

  static Future<void> showCommandCenter() async {
    await _invoke('showCommandCenter');
  }

  static Future<void> setAlwaysOnTop(bool value) async {
    await _invoke('setAlwaysOnTop', value);
  }

  static Future<void> hide() async {
    await _invoke('hide');
  }

  static Future<Uint8List?> captureScreen() async {
    if (!supported) return null;
    try {
      return await _channel.invokeMethod<Uint8List>('captureScreen');
    } on MissingPluginException {
      return null;
    } on PlatformException {
      return null;
    }
  }

  static Future<bool> openPath(String path) => _pathAction('openPath', path);

  static Future<bool> showInFolder(String path) =>
      _pathAction('showInFolder', path);

  static Future<bool> _pathAction(String method, String path) async {
    if (!supported) return false;
    final file = File(path);
    if (!file.isAbsolute || !await file.exists()) return false;
    try {
      return await _channel.invokeMethod<bool>(method, file.path) ?? false;
    } on MissingPluginException {
      return false;
    } on PlatformException {
      return false;
    }
  }

  static Future<void> _invoke(String method, [Object? arguments]) async {
    if (!supported) return;
    try {
      await _channel.invokeMethod<void>(method, arguments);
    } on MissingPluginException {
      // Widget tests and non-native debug hosts do not install the bridge.
    } on PlatformException {
      // Keep the shared Flutter UI usable if native window control fails.
    }
  }
}
