import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../config/hermes_config.dart';
import '../services/assistant_service.dart';
import '../services/local_command_service.dart';
import '../theme/troika_theme.dart';
import 'chat_screen.dart';
import 'commands_screen.dart';
import 'local_documents_screen.dart';
import 'settings_screen.dart';
import 'voice_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  String _mode = 'normal';
  AssistantService? _assistant;
  bool _openingCommandScreen = false;

  @override
  void initState() {
    super.initState();
    _loadMode();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (HermesConfig.serverUrl.trim().isEmpty && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Локальный режим: команды работают без сервера'),
            duration: Duration(seconds: 3),
          ),
        );
      }
    });
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    final assistant = context.read<AssistantService>();
    if (identical(_assistant, assistant)) return;
    _assistant?.removeListener(_handleUiAction);
    _assistant = assistant..addListener(_handleUiAction);
  }

  void _handleUiAction() {
    final request = _assistant?.takePendingUiAction();
    if (request == null || !mounted || _openingCommandScreen) return;
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted) return;
      _openingCommandScreen = true;
      await _open(
        LocalDocumentsScreen(
          initialPresentation: request.action == 'create_presentation',
          initialPrompt: request.prompt,
        ),
      );
      _openingCommandScreen = false;
    });
  }

  Future<void> _loadMode() async {
    final value = await LocalCommandService.currentMode();
    if (mounted) setState(() => _mode = value);
  }

  Future<void> _open(Widget screen) async {
    await Navigator.push(context, MaterialPageRoute(builder: (_) => screen));
    _loadMode();
  }

  @override
  void dispose() {
    _assistant?.removeListener(_handleUiAction);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final assistant = context.watch<AssistantService>();
    final wide = MediaQuery.sizeOf(context).width >= 900;
    final chat = ChatScreen(
      onOpenCommands: () => _open(const CommandsScreen()),
      onOpenDocuments: () => _open(const LocalDocumentsScreen()),
    );

    return Scaffold(
      backgroundColor: TroikaColors.bg,
      body: SafeArea(
        bottom: false,
        child: wide
            ? Row(
                children: [
                  SizedBox(width: 210, child: _DesktopSidebar(open: _open)),
                  const VerticalDivider(width: 1, color: Colors.white10),
                  Expanded(
                    child: Column(
                      children: [
                        _Header(state: assistant.state, mode: _mode),
                        Expanded(child: chat),
                      ],
                    ),
                  ),
                  const VerticalDivider(width: 1, color: Colors.white10),
                  SizedBox(
                    width: 270,
                    child: _RightRail(open: _open, mode: _mode),
                  ),
                ],
              )
            : Column(
                children: [
                  _Header(state: assistant.state, mode: _mode),
                  Expanded(child: chat),
                ],
              ),
      ),
      bottomNavigationBar: wide
          ? null
          : NavigationBar(
              height: 64,
              selectedIndex: 0,
              backgroundColor: TroikaColors.surface,
              indicatorColor: TroikaColors.brand.withOpacity(0.16),
              onDestinationSelected: (index) {
                if (index == 1) _open(const CommandsScreen());
                if (index == 2) _open(const LocalDocumentsScreen());
                if (index == 3) _open(const SettingsScreen());
              },
              destinations: const [
                NavigationDestination(
                  icon: Icon(Icons.home_outlined),
                  selectedIcon: Icon(Icons.home),
                  label: 'Сегодня',
                ),
                NavigationDestination(
                  icon: Icon(Icons.grid_view_outlined),
                  label: 'Команды',
                ),
                NavigationDestination(
                  icon: Icon(Icons.description_outlined),
                  label: 'Документы',
                ),
                NavigationDestination(
                  icon: Icon(Icons.settings_outlined),
                  label: 'Настройки',
                ),
              ],
            ),
    );
  }
}

class _Header extends StatelessWidget {
  final AssistantState state;
  final String mode;

  const _Header({required this.state, required this.mode});

  @override
  Widget build(BuildContext context) {
    final accent = TroikaColors.forState(state);
    final modeName = switch (mode) {
      'protocol' => 'Протокол',
      'rest' => 'Отдых',
      _ => 'Локально',
    };
    return Container(
      height: 62,
      padding: const EdgeInsets.symmetric(horizontal: 20),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: Colors.white10)),
      ),
      child: Row(
        children: [
          Container(
            width: 9,
            height: 9,
            decoration: BoxDecoration(shape: BoxShape.circle, color: accent),
          ),
          const SizedBox(width: 11),
          Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Тройка на связи',
                style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
              ),
              Text(
                state == AssistantState.idle
                    ? '$modeName · без сервера'
                    : TroikaColors.hint(state),
                style: const TextStyle(
                  color: TroikaColors.textMuted,
                  fontSize: 12,
                ),
              ),
            ],
          ),
          const Spacer(),
          IconButton(
            tooltip: 'Очистить диалог',
            onPressed: () =>
                context.read<AssistantService>().clearConversation(),
            icon: const Icon(Icons.add_comment_outlined),
          ),
        ],
      ),
    );
  }
}

class _DesktopSidebar extends StatelessWidget {
  final Future<void> Function(Widget screen) open;

  const _DesktopSidebar({required this.open});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(14, 18, 14, 14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Padding(
            padding: EdgeInsets.fromLTRB(10, 6, 10, 24),
            child: Text(
              'Тройка',
              style: TextStyle(fontSize: 20, fontWeight: FontWeight.w600),
            ),
          ),
          const _NavItem(
            icon: Icons.home_outlined,
            label: 'Сегодня',
            active: true,
          ),
          _NavItem(
            icon: Icons.grid_view_outlined,
            label: 'Команды',
            onTap: () => open(const CommandsScreen()),
          ),
          _NavItem(
            icon: Icons.description_outlined,
            label: 'Документы',
            onTap: () => open(const LocalDocumentsScreen()),
          ),
          const Spacer(),
          _NavItem(
            icon: Icons.record_voice_over_outlined,
            label: 'Голос',
            onTap: () => open(const VoiceScreen()),
          ),
          _NavItem(
            icon: Icons.settings_outlined,
            label: 'Настройки',
            onTap: () => open(const SettingsScreen()),
          ),
        ],
      ),
    );
  }
}

class _NavItem extends StatelessWidget {
  final IconData icon;
  final String label;
  final bool active;
  final VoidCallback? onTap;

  const _NavItem({
    required this.icon,
    required this.label,
    this.active = false,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 5),
      child: ListTile(
        dense: true,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(11)),
        tileColor: active ? TroikaColors.brand.withOpacity(0.11) : null,
        leading: Icon(
          icon,
          color: active ? TroikaColors.brand : TroikaColors.textMuted,
        ),
        title: Text(label),
        onTap: onTap,
      ),
    );
  }
}

class _RightRail extends StatelessWidget {
  final Future<void> Function(Widget screen) open;
  final String mode;

  const _RightRail({required this.open, required this.mode});

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        const Text('Быстрые действия', style: _railTitle),
        const SizedBox(height: 12),
        _ActionTile(
          icon: Icons.description_outlined,
          title: 'Создать документ',
          onTap: () => open(const LocalDocumentsScreen()),
        ),
        _ActionTile(
          icon: Icons.slideshow_outlined,
          title: 'Создать презентацию',
          onTap: () => open(const LocalDocumentsScreen()),
        ),
        _ActionTile(
          icon: Icons.grid_view_outlined,
          title: 'Все команды',
          onTap: () => open(const CommandsScreen()),
        ),
        const SizedBox(height: 24),
        const Text('Текущий режим', style: _railTitle),
        const SizedBox(height: 10),
        Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            color: TroikaColors.surface,
            borderRadius: BorderRadius.circular(13),
            border: Border.all(color: Colors.white10),
          ),
          child: Text(
            mode == 'rest'
                ? 'Отдых · без голосовых ответов'
                : mode == 'protocol'
                    ? 'Протокол · короткие ответы'
                    : 'Обычный · команды и голос',
            style: const TextStyle(color: TroikaColors.textMuted),
          ),
        ),
      ],
    );
  }
}

const _railTitle = TextStyle(fontSize: 16, fontWeight: FontWeight.w600);

class _ActionTile extends StatelessWidget {
  final IconData icon;
  final String title;
  final VoidCallback onTap;

  const _ActionTile({
    required this.icon,
    required this.title,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: ListTile(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
        tileColor: TroikaColors.surface,
        leading: Icon(icon, color: TroikaColors.brand),
        title: Text(title, style: const TextStyle(fontSize: 14)),
        trailing: const Icon(Icons.chevron_right, size: 18),
        onTap: onTap,
      ),
    );
  }
}
