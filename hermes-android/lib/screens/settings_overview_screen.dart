import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../config/troika_config.dart';
import '../services/assistant_service.dart';
import '../theme/troika_theme.dart';
import 'memory_screen.dart';
import 'settings_screen.dart';
import 'voice_screen.dart';

class SettingsOverviewScreen extends StatelessWidget {
  final VoidCallback? onSignedOut;

  const SettingsOverviewScreen({super.key, this.onSignedOut});

  Future<void> _open(BuildContext context, Widget screen) {
    return Navigator.push(context, MaterialPageRoute(builder: (_) => screen));
  }

  @override
  Widget build(BuildContext context) {
    final assistant = context.watch<AssistantService>();
    final account = TroikaConfig.accountEmail.trim();

    return Scaffold(
      backgroundColor: TroikaColors.bg,
      appBar: AppBar(
        title: const Text('Настройки'),
        backgroundColor: TroikaColors.bg,
        surfaceTintColor: Colors.transparent,
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 32),
        children: [
          _SettingsCard(
            title: 'Голос',
            children: [
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('Слушать «Тройка» в фоне'),
                subtitle: const Text('Можно отключить в любой момент'),
                value: assistant.wakeWordEnabled,
                onChanged: assistant.setWakeWordEnabled,
              ),
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.record_voice_over_outlined),
                title: const Text('Выбрать голос'),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => _open(context, const VoiceScreen()),
              ),
            ],
          ),
          _SettingsCard(
            title: 'Память',
            children: [
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.memory_outlined),
                title: const Text('Что помнит Тройка'),
                subtitle: const Text('Посмотреть, изменить или удалить'),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => _open(context, const MemoryScreen()),
              ),
            ],
          ),
          _SettingsCard(
            title: 'Разрешения',
            children: [
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.shield_outlined),
                title: const Text('Доступы устройства'),
                subtitle: Text(
                  'Телефон: ${TroikaConfig.phoneControlEnabled ? "включён" : "выключен"} · '
                  'местоположение: ${TroikaConfig.locationContextEnabled ? "включено" : "выключено"}',
                ),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => _open(
                  context,
                  SettingsScreen(
                    onSignedOut: onSignedOut,
                    section: SettingsSection.permissions,
                  ),
                ),
              ),
            ],
          ),
          _SettingsCard(
            title: 'Аккаунт и данные',
            children: [
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.account_circle_outlined),
                title: Text(account.isEmpty ? 'Локальный профиль' : account),
                subtitle: const Text('Устройства, экспорт и удаление данных'),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => _open(
                  context,
                  SettingsScreen(
                    onSignedOut: onSignedOut,
                    section: SettingsSection.account,
                  ),
                ),
              ),
            ],
          ),
          _SettingsCard(
            title: 'Дополнительно',
            children: [
              ListTile(
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.tune_outlined),
                title: const Text('Расширенные настройки'),
                subtitle: const Text('Подключение, тонкая настройка и доступы'),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => _open(
                  context,
                  SettingsScreen(onSignedOut: onSignedOut),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _SettingsCard extends StatelessWidget {
  final String title;
  final List<Widget> children;

  const _SettingsCard({required this.title, required this.children});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Material(
        color: TroikaColors.surface,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(16),
          side: const BorderSide(color: Colors.white10),
        ),
        clipBehavior: Clip.antiAlias,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 14, 16, 6),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: const TextStyle(
                  fontSize: 17,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(height: 4),
              ...children,
            ],
          ),
        ),
      ),
    );
  }
}
