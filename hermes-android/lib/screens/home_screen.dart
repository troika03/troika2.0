import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../config/troika_config.dart';
import '../services/assistant_service.dart';
import '../services/assistant_result.dart';
import '../services/troika_api_service.dart';
import '../theme/troika_theme.dart';
import '../widgets/status_orb.dart';
import 'chat_screen.dart';
import 'commands_screen.dart';
import 'assistant_hub_screen.dart';
import 'files_screen.dart';
import 'local_documents_screen.dart';
import 'settings_overview_screen.dart';
import 'voice_screen.dart';

class HomeScreen extends StatefulWidget {
  final VoidCallback? onSignedOut;

  const HomeScreen({super.key, this.onSignedOut});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  AssistantService? _assistant;
  bool _openingCommandScreen = false;
  RunApprovalRequest? _shownApproval;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (TroikaConfig.serverUrl.trim().isEmpty && mounted) {
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

  Future<void> _open(Widget screen) async {
    await Navigator.push(context, MaterialPageRoute(builder: (_) => screen));
  }

  Future<void> _openChat() => _open(
        Scaffold(
          backgroundColor: TroikaColors.bg,
          appBar: AppBar(
            title: const Text('Текст'),
            backgroundColor: TroikaColors.bg,
            surfaceTintColor: Colors.transparent,
          ),
          body: ChatScreen(
            onOpenCommands: () => _open(const CommandsScreen()),
            onOpenDocuments: () => _open(const LocalDocumentsScreen()),
          ),
        ),
      );

  void _watchApproval(AssistantService assistant) {
    final approval = assistant.pendingApproval;
    if (approval == null) {
      _shownApproval = null;
      return;
    }
    if (identical(_shownApproval, approval)) return;
    _shownApproval = approval;
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted || ModalRoute.of(context)?.isCurrent != true) {
        _shownApproval = null;
        return;
      }
      final choice = await showDialog<String>(
        context: context,
        barrierDismissible: false,
        builder: (dialogContext) => AlertDialog(
          title: const Text('Нужно разрешение'),
          content: Text(
            approval.description.trim().isEmpty
                ? approval.action
                : approval.description,
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, 'deny'),
              child: const Text('Отмена'),
            ),
            if (approval.choices.contains('once'))
              FilledButton(
                onPressed: () => Navigator.pop(dialogContext, 'once'),
                child: const Text('Разрешить один раз'),
              ),
          ],
        ),
      );
      assistant.resolvePendingApproval(choice ?? 'deny');
    });
  }

  @override
  void dispose() {
    _assistant?.removeListener(_handleUiAction);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final assistant = context.watch<AssistantService>();
    _watchApproval(assistant);
    final wide = MediaQuery.sizeOf(context).width >= 900;
    final connected = TroikaConfig.serverUrl.trim().isNotEmpty;
    final voiceHome = _VoiceHome(
      assistant: assistant,
      onOpenText: _openChat,
      onOpenFiles: () => _open(const FilesScreen()),
      onOpenSaved: () => _open(const AssistantHubScreen()),
    );

    return Scaffold(
      backgroundColor: TroikaColors.bg,
      body: SafeArea(
        bottom: false,
        child: wide
            ? Row(
                children: [
                  SizedBox(
                    width: 210,
                    child: _DesktopSidebar(
                      open: _open,
                      onSignedOut: widget.onSignedOut,
                    ),
                  ),
                  const VerticalDivider(width: 1, color: Colors.white10),
                  Expanded(
                    child: Column(
                      children: [
                        _Header(
                          state: assistant.state,
                          connected: connected,
                          onSettings: () => _open(
                            SettingsOverviewScreen(
                              onSignedOut: widget.onSignedOut,
                            ),
                          ),
                        ),
                        Expanded(child: voiceHome),
                      ],
                    ),
                  ),
                  const VerticalDivider(width: 1, color: Colors.white10),
                  SizedBox(
                    width: 270,
                    child: _RightRail(open: _open),
                  ),
                ],
              )
            : Column(
                children: [
                  _Header(
                    state: assistant.state,
                    connected: connected,
                    onSettings: () => _open(
                      SettingsOverviewScreen(onSignedOut: widget.onSignedOut),
                    ),
                  ),
                  Expanded(child: voiceHome),
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
                if (index == 3) {
                  _open(
                    SettingsOverviewScreen(onSignedOut: widget.onSignedOut),
                  );
                }
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
  final bool connected;
  final VoidCallback onSettings;

  const _Header({
    required this.state,
    required this.connected,
    required this.onSettings,
  });

  @override
  Widget build(BuildContext context) {
    final accent = TroikaColors.forState(state);
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
          const Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Тройка',
                style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
              ),
            ],
          ),
          const Spacer(),
          Text(
            connected ? 'На связи' : 'Локально',
            style: const TextStyle(
              color: TroikaColors.textMuted,
              fontSize: 12,
            ),
          ),
          const SizedBox(width: 4),
          IconButton(
            tooltip: 'Профиль и настройки',
            onPressed: onSettings,
            icon: const Icon(Icons.account_circle_outlined),
          ),
        ],
      ),
    );
  }
}

class _VoiceHome extends StatelessWidget {
  final AssistantService assistant;
  final VoidCallback onOpenText;
  final VoidCallback onOpenFiles;
  final VoidCallback onOpenSaved;

  const _VoiceHome({
    required this.assistant,
    required this.onOpenText,
    required this.onOpenFiles,
    required this.onOpenSaved,
  });

  @override
  Widget build(BuildContext context) {
    final label = _voiceStateLabel(assistant);
    final hint = _voiceStateHint(assistant);
    return LayoutBuilder(
      builder: (context, constraints) => SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(20, 24, 20, 32),
        child: Center(
          child: ConstrainedBox(
            constraints: BoxConstraints(
              maxWidth: 720,
              minHeight: (constraints.maxHeight - 56)
                  .clamp(0, double.infinity)
                  .toDouble(),
            ),
            child: Column(
              children: [
                const Text(
                  'Что сделать?',
                  style: TextStyle(
                    fontSize: 28,
                    height: 1.1,
                    fontWeight: FontWeight.w600,
                    letterSpacing: -0.5,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  label,
                  style: TextStyle(
                    color: TroikaColors.forState(assistant.state),
                    fontSize: 15,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  hint,
                  textAlign: TextAlign.center,
                  style: const TextStyle(
                    color: TroikaColors.textMuted,
                    fontSize: 14,
                  ),
                ),
                const SizedBox(height: 4),
                _OrbButton(assistant: assistant),
                TextButton.icon(
                  onPressed: onOpenText,
                  icon: const Icon(Icons.keyboard_outlined, size: 18),
                  label: const Text('Текст'),
                ),
                const SizedBox(height: 16),
                _CurrentCards(
                  assistant: assistant,
                  onOpenText: onOpenText,
                  onOpenFiles: onOpenFiles,
                  onOpenSaved: onOpenSaved,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _OrbButton extends StatelessWidget {
  final AssistantService assistant;

  const _OrbButton({required this.assistant});

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      label: 'Говорить с Тройкой',
      hint: _voiceStateHint(assistant),
      child: Tooltip(
        message: _voiceStateHint(assistant),
        child: InkResponse(
          radius: 116,
          containedInkWell: true,
          highlightShape: BoxShape.circle,
          onTap: () => _handleOrbTap(assistant),
          child: StatusOrb(state: assistant.state),
        ),
      ),
    );
  }
}

Future<void> _handleOrbTap(AssistantService assistant) async {
  switch (assistant.state) {
    case AssistantState.idle:
    case AssistantState.error:
      return assistant.startManualRecording();
    case AssistantState.recording:
      return assistant.stopRecordingAndProcess();
    case AssistantState.wakeDetected:
    case AssistantState.processing:
    case AssistantState.speaking:
      return assistant.interrupt();
  }
}

String _voiceStateLabel(AssistantService assistant) {
  return switch (assistant.state) {
    AssistantState.idle => 'Готово',
    AssistantState.wakeDetected => 'Слушаю',
    AssistantState.recording => 'Слушаю',
    AssistantState.processing =>
      _isActing(assistant) ? 'Выполняю' : 'Разбираюсь',
    AssistantState.speaking => 'Говорю',
    AssistantState.error => 'Ошибка',
  };
}

String _voiceStateHint(AssistantService assistant) {
  return switch (assistant.state) {
    AssistantState.idle => 'Нажми и скажи, что сделать',
    AssistantState.wakeDetected => 'Да, слушаю',
    AssistantState.recording => 'Говори. Нажми ещё раз, чтобы отправить',
    AssistantState.processing =>
      _isActing(assistant) ? 'Выполняю задачу' : 'Понимаю задачу',
    AssistantState.speaking => 'Нажми, чтобы прервать ответ',
    AssistantState.error => assistant.errorMessage.isEmpty
        ? 'Нажми, чтобы попробовать снова'
        : assistant.errorMessage,
  };
}

bool _isActing(AssistantService assistant) {
  return assistant.isActing;
}

class _CurrentCards extends StatelessWidget {
  final AssistantService assistant;
  final VoidCallback onOpenText;
  final VoidCallback onOpenFiles;
  final VoidCallback onOpenSaved;

  const _CurrentCards({
    required this.assistant,
    required this.onOpenText,
    required this.onOpenFiles,
    required this.onOpenSaved,
  });

  @override
  Widget build(BuildContext context) {
    final cards = <Widget>[];
    final approval = assistant.pendingApproval;
    if (approval != null) {
      cards.add(_ApprovalCard(assistant: assistant, approval: approval));
    }
    if (assistant.state != AssistantState.idle && approval == null) {
      cards.add(
        _HomeCard(
          icon: assistant.state == AssistantState.error
              ? Icons.error_outline
              : Icons.bolt_outlined,
          title: _voiceStateLabel(assistant),
          body: _voiceStateHint(assistant),
          accent: assistant.state == AssistantState.error
              ? TroikaColors.error
              : TroikaColors.brand,
        ),
      );
    }
    final result = assistant.lastResult;
    if (result != null && result.summary.isNotEmpty) {
      cards.add(
        _HomeCard(
          icon: _resultIcon(result.kind),
          title: result.title,
          body: result.summary,
          actionLabel: result.kind == AssistantResultKind.file
              ? 'Открыть файлы'
              : result.kind == AssistantResultKind.saved
                  ? 'Открыть задачи'
                  : result.kind == AssistantResultKind.answer
                      ? 'Открыть текст'
                      : 'Подробнее',
          onAction: result.kind == AssistantResultKind.file
              ? onOpenFiles
              : result.kind == AssistantResultKind.saved
                  ? onOpenSaved
                  : onOpenText,
        ),
      );
    }
    if (assistant.lastUserText.trim().isNotEmpty && cards.length < 3) {
      cards.add(
        _HomeCard(
          icon: Icons.schedule_outlined,
          title: 'Последняя задача',
          body: _summary(assistant.lastUserText),
        ),
      );
    }
    if (cards.isEmpty) return const SizedBox.shrink();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Text(
          'Сейчас',
          style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
        ),
        const SizedBox(height: 12),
        ...cards.take(3).expand(
              (card) => [card, const SizedBox(height: 8)],
            ),
      ],
    );
  }
}

class _ApprovalCard extends StatelessWidget {
  final AssistantService assistant;
  final RunApprovalRequest approval;

  const _ApprovalCard({required this.assistant, required this.approval});

  @override
  Widget build(BuildContext context) {
    return _HomeCard(
      icon: Icons.shield_outlined,
      title: 'Нужно разрешение',
      body: approval.description.trim().isEmpty
          ? approval.action
          : approval.description,
      footer: Wrap(
        alignment: WrapAlignment.end,
        spacing: 8,
        runSpacing: 4,
        children: [
          TextButton(
            onPressed: () => assistant.resolvePendingApproval('deny'),
            child: const Text('Отмена'),
          ),
          if (approval.choices.contains('once'))
            FilledButton(
              onPressed: () => assistant.resolvePendingApproval('once'),
              child: const Text('Разрешить один раз'),
            ),
        ],
      ),
    );
  }
}

class _HomeCard extends StatelessWidget {
  final IconData icon;
  final String title;
  final String body;
  final Color accent;
  final String? actionLabel;
  final VoidCallback? onAction;
  final Widget? footer;

  const _HomeCard({
    required this.icon,
    required this.title,
    required this.body,
    this.accent = TroikaColors.brand,
    this.actionLabel,
    this.onAction,
    this.footer,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: TroikaColors.surface,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: accent.withValues(alpha: 0.18)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(
              color: accent.withValues(alpha: 0.11),
              shape: BoxShape.circle,
            ),
            child: Icon(icon, color: accent, size: 21),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: const TextStyle(fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 4),
                Text(
                  body,
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    color: TroikaColors.textMuted,
                    height: 1.35,
                  ),
                ),
                if (actionLabel != null && onAction != null)
                  Align(
                    alignment: Alignment.centerRight,
                    child: TextButton(
                      onPressed: onAction,
                      child: Text(actionLabel!),
                    ),
                  ),
                if (footer != null) ...[
                  const SizedBox(height: 8),
                  footer!,
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

String _summary(String value) {
  final compact = value.replaceAll(RegExp(r'\s+'), ' ').trim();
  return compact.length <= 180 ? compact : '${compact.substring(0, 179)}…';
}

IconData _resultIcon(AssistantResultKind kind) {
  return switch (kind) {
    AssistantResultKind.answer => Icons.chat_bubble_outline,
    AssistantResultKind.action => Icons.check_circle_outline,
    AssistantResultKind.file => Icons.insert_drive_file_outlined,
    AssistantResultKind.saved => Icons.bookmark_added_outlined,
  };
}

class _DesktopSidebar extends StatelessWidget {
  final Future<void> Function(Widget screen) open;
  final VoidCallback? onSignedOut;

  const _DesktopSidebar({required this.open, this.onSignedOut});

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
            onTap: () => open(
              SettingsOverviewScreen(onSignedOut: onSignedOut),
            ),
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

  const _RightRail({required this.open});

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
