import 'dart:io' show Platform;

import 'package:flutter/material.dart';

import '../config/troika_config.dart';
import '../services/windows_shell_service.dart';

class InterfaceSettingsScreen extends StatefulWidget {
  final VoidCallback? onChanged;

  const InterfaceSettingsScreen({super.key, this.onChanged});

  @override
  State<InterfaceSettingsScreen> createState() =>
      _InterfaceSettingsScreenState();
}

class _InterfaceSettingsScreenState extends State<InterfaceSettingsScreen> {
  late String _theme = TroikaConfig.themeMode;
  late double _scale = TroikaConfig.textScale;
  late String _windowsHotkey = TroikaConfig.windowsHotkey;
  late bool _windowsPinned = TroikaConfig.windowsAlwaysOnTop;

  Future<void> _setTheme(String? value) async {
    if (value == null) return;
    await TroikaConfig.setThemeMode(value);
    setState(() => _theme = value);
    widget.onChanged?.call();
  }

  Future<void> _setScale(double value) async {
    await TroikaConfig.setTextScale(value);
    setState(() => _scale = value);
    widget.onChanged?.call();
  }

  Future<void> _setWindowsHotkey(String? value) async {
    if (value == null) return;
    final registered = await WindowsShellService.registerHotkey(value);
    if (!mounted) return;
    if (!registered) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Эта комбинация уже занята')),
      );
      return;
    }
    await TroikaConfig.setWindowsHotkey(value);
    if (!mounted) return;
    setState(() => _windowsHotkey = value);
  }

  Future<void> _setWindowsPinned(bool value) async {
    await TroikaConfig.setWindowsAlwaysOnTop(value);
    await WindowsShellService.setAlwaysOnTop(value);
    if (!mounted) return;
    setState(() => _windowsPinned = value);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Интерфейс')),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          const Text('Тема', style: TextStyle(fontWeight: FontWeight.w600)),
          const SizedBox(height: 10),
          SegmentedButton<String>(
            segments: const [
              ButtonSegment(value: 'system', label: Text('Система')),
              ButtonSegment(value: 'dark', label: Text('Тёмная')),
              ButtonSegment(value: 'light', label: Text('Светлая')),
            ],
            selected: {_theme},
            onSelectionChanged: (values) => _setTheme(values.first),
          ),
          const Divider(),
          const ListTile(
            contentPadding: EdgeInsets.zero,
            title: Text('Язык'),
            subtitle: Text('Русский'),
          ),
          const Divider(),
          Text('Размер текста · ${(_scale * 100).round()}%'),
          Slider(
            value: _scale,
            min: 0.9,
            max: 1.25,
            divisions: 7,
            label: '${(_scale * 100).round()}%',
            onChanged: _setScale,
          ),
          if (Platform.isWindows) ...[
            const Divider(),
            const Text(
              'Compact Assistant',
              style: TextStyle(fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: 8),
            DropdownButtonFormField<String>(
              initialValue: _windowsHotkey,
              decoration: const InputDecoration(
                labelText: 'Глобальная горячая клавиша',
              ),
              items: const [
                DropdownMenuItem(
                  value: 'ctrlAltSpace',
                  child: Text('Ctrl + Alt + Space'),
                ),
                DropdownMenuItem(
                  value: 'ctrlShiftSpace',
                  child: Text('Ctrl + Shift + Space'),
                ),
                DropdownMenuItem(
                  value: 'ctrlAltT',
                  child: Text('Ctrl + Alt + T'),
                ),
              ],
              onChanged: _setWindowsHotkey,
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Compact поверх окон'),
              subtitle: const Text('Можно переключить кнопкой-булавкой'),
              value: _windowsPinned,
              onChanged: _setWindowsPinned,
            ),
          ],
        ],
      ),
    );
  }
}
