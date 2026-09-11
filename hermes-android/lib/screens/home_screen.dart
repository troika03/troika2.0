import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../config/hermes_config.dart';
import '../services/assistant_service.dart';
import '../theme/troika_theme.dart';
import 'chat_screen.dart';
import 'settings_screen.dart';
import 'history_screen.dart';
import 'files_screen.dart';
import 'assistant_hub_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  @override
  void initState() {
    super.initState();
    // Первый запуск: сервер ещё не настроен — мягко уводим новичка в Настройки.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (HermesConfig.serverUrl.trim().isEmpty && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Укажи адрес сервера, чтобы начать'),
            duration: Duration(seconds: 4),
          ),
        );
        Navigator.push(
          context,
          MaterialPageRoute(builder: (_) => const SettingsScreen()),
        );
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final assistant = context.watch<AssistantService>();
    final accent = TroikaColors.forState(assistant.state);

    return Scaffold(
      backgroundColor: TroikaColors.bg,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            _TopBar(accent: accent),
            // Тонкая подпись состояния — компактно, не мешает чату.
            _StatusLine(state: assistant.state),
            const Expanded(child: ChatScreen()),
          ],
        ),
      ),
    );
  }
}

class _StatusLine extends StatelessWidget {
  final AssistantState state;
  const _StatusLine({required this.state});

  @override
  Widget build(BuildContext context) {
    if (state == AssistantState.idle) return const SizedBox(height: 2);
    return Padding(
      padding: const EdgeInsets.only(bottom: 2),
      child: Text(
        TroikaColors.hint(state),
        style: TextStyle(
          color: state == AssistantState.error
              ? TroikaColors.error.withOpacity(0.9)
              : TroikaColors.textMuted,
          fontSize: 12,
          letterSpacing: 0.2,
        ),
      ),
    );
  }
}

class _TopBar extends StatelessWidget {
  final Color accent;
  const _TopBar({required this.accent});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(left: 20, right: 4, top: 8, bottom: 2),
      child: Row(
        children: [
          Container(
            width: 9,
            height: 9,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: accent,
              boxShadow: [
                BoxShadow(color: accent.withOpacity(0.6), blurRadius: 8),
              ],
            ),
          ),
          const SizedBox(width: 11),
          const Text(
            'Тройка',
            style: TextStyle(
              color: TroikaColors.text,
              fontSize: 19,
              fontWeight: FontWeight.w600,
              letterSpacing: 0.3,
            ),
          ),
          const Spacer(),
          IconButton(
            icon: const Icon(Icons.add_comment_outlined),
            color: TroikaColors.textMuted,
            iconSize: 21,
            tooltip: 'Очистить ленту',
            onPressed: () =>
                context.read<AssistantService>().clearConversation(),
          ),
          IconButton(
            icon: const Icon(Icons.folder_outlined),
            color: TroikaColors.textMuted,
            iconSize: 22,
            tooltip: 'Файлы Тройки',
            onPressed: () => Navigator.push(
              context,
              MaterialPageRoute(builder: (_) => const FilesScreen()),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.history_rounded),
            color: TroikaColors.textMuted,
            iconSize: 22,
            onPressed: () => Navigator.push(
              context,
              MaterialPageRoute(builder: (_) => const HistoryScreen()),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.inbox_outlined),
            color: TroikaColors.textMuted,
            iconSize: 22,
            tooltip: 'Помощник: проекты и напоминания',
            onPressed: () => Navigator.push(
              context,
              MaterialPageRoute(builder: (_) => const AssistantHubScreen()),
            ),
          ),
          IconButton(
            icon: const Icon(Icons.settings_outlined),
            color: TroikaColors.textMuted,
            iconSize: 22,
            onPressed: () => Navigator.push(
              context,
              MaterialPageRoute(builder: (_) => const SettingsScreen()),
            ),
          ),
        ],
      ),
    );
  }
}
