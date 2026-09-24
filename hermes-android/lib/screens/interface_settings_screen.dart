import 'package:flutter/material.dart';

import '../config/troika_config.dart';

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
        ],
      ),
    );
  }
}
