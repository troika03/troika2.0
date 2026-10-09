import 'dart:async';
import 'dart:convert';
import 'dart:io' show Platform;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../config/troika_config.dart';
import '../services/assistant_service.dart';
import '../services/assistant_result.dart';
import '../services/troika_api_service.dart';
import '../services/windows_shell_service.dart';
import '../theme/troika_theme.dart';
import '../widgets/status_orb.dart';
import '../widgets/troika_page.dart';
import '../widgets/web_sources_view.dart';
import 'chat_screen.dart';
import 'commands_screen.dart';
import 'assistant_hub_screen.dart';
import 'files_screen.dart';
import 'files_hub_screen.dart';
import 'history_screen.dart';
import 'local_documents_screen.dart';
import 'memory_screen.dart';
import 'settings_overview_screen.dart';
import 'voice_screen.dart';

class HomeScreen extends StatefulWidget {
  final VoidCallback? onSignedOut;
  final VoidCallback? onAppearanceChanged;
  final bool? windowsShellOverride;

  const HomeScreen({
    super.key,
    this.onSignedOut,
    this.onAppearanceChanged,
    this.windowsShellOverride,
  });

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  AssistantService? _assistant;
  bool _openingCommandScreen = false;
  bool _windowsShellInitialized = false;
  bool _windowsCompact = false;
  bool _windowsPinned = TroikaConfig.windowsAlwaysOnTop;
  int _mobileTab = 0;
  RunApprovalRequest? _shownApproval;
  bool _approvalDialogOpen = false;

  bool get _isWindows => widget.windowsShellOverride ?? Platform.isWindows;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (TroikaConfig.serverUrl.trim().isEmpty && mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('Тройка готова к локальным командам'),
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
    _showPendingApproval();
    if (_isWindows && !_windowsShellInitialized) {
      _windowsShellInitialized = true;
      unawaited(WindowsShellService.initialize(_handleWindowsHotkey));
    }
  }

  void _handleUiAction() {
    _showPendingApproval();
    final request = _assistant?.takePendingUiAction();
    if (request == null || !mounted || _openingCommandScreen) return;
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted) return;
      _openingCommandScreen = true;
      if (request.action == 'capture_screen_for_vision') {
        await _captureScreenForVision();
      } else {
        await _open(
          LocalDocumentsScreen(
            initialPresentation: request.action == 'create_presentation',
            initialPrompt: request.prompt,
          ),
        );
      }
      _openingCommandScreen = false;
    });
  }

  void _showPendingApproval() {
    final assistant = _assistant;
    final approval = assistant?.pendingApproval;
    if (approval == null) {
      _shownApproval = null;
      return;
    }
    if (!mounted ||
        _approvalDialogOpen ||
        identical(_shownApproval, approval)) {
      return;
    }
    _shownApproval = approval;
    _approvalDialogOpen = true;
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted) {
        _approvalDialogOpen = false;
        return;
      }
      final choice = await showDialog<String>(
        context: context,
        barrierDismissible: false,
        builder: (dialogContext) => AlertDialog(
          title: const Text('Подтвердить важное действие'),
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
      _approvalDialogOpen = false;
      assistant?.resolvePendingApproval(choice ?? 'deny');
    });
  }

  Future<void> _handleWindowsHotkey() async {
    final assistant = _assistant;
    if (!mounted || assistant == null) return;
    if (_windowsCompact && assistant.state == AssistantState.recording) {
      await assistant.stopRecordingAndProcess();
      return;
    }
    if (_windowsCompact && assistant.state != AssistantState.idle) {
      await assistant.interrupt();
      return;
    }
    if (!_windowsCompact) {
      setState(() => _windowsCompact = true);
      await WindowsShellService.showCompact(alwaysOnTop: _windowsPinned);
    }
    await assistant.startManualRecording();
  }

  Future<void> _showCompact() async {
    setState(() => _windowsCompact = true);
    await WindowsShellService.showCompact(alwaysOnTop: _windowsPinned);
  }

  Future<void> _showCommandCenter() async {
    setState(() => _windowsCompact = false);
    await WindowsShellService.showCommandCenter();
  }

  Future<void> _hideCompact() => WindowsShellService.hide();

  Future<void> _togglePinned() async {
    final value = !_windowsPinned;
    await TroikaConfig.setWindowsAlwaysOnTop(value);
    if (!mounted) return;
    setState(() => _windowsPinned = value);
    await WindowsShellService.setAlwaysOnTop(value);
  }

  Future<void> _openFromCompact(Widget screen) async {
    await _showCommandCenter();
    if (mounted) await _open(screen);
  }

  Future<void> _captureScreenForVision() async {
    if (!_isWindows) return;
    if (TroikaConfig.serverUrl.trim().isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
            content: Text('Для анализа снимка нужен AI-подключение')),
      );
      return;
    }
    final approved = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Передать снимок в AI?'),
        content: const Text(
          'Тройка сделает один снимок всех экранов и отправит его для анализа. '
          'Защищённые окна Windows могут отображаться чёрным.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('Отмена'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('Разрешить один раз'),
          ),
        ],
      ),
    );
    if (approved != true || !mounted) return;
    final bytes = await WindowsShellService.captureScreen();
    if (!mounted) return;
    if (bytes == null || bytes.isEmpty || bytes.length > 10 * 1024 * 1024) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Не удалось подготовить снимок экрана')),
      );
      return;
    }
    await _assistant?.sendTextQuery(
      'Проанализируй этот снимок экрана.',
      imageDataUrls: ['data:image/png;base64,${base64Encode(bytes)}'],
    );
  }

  Future<void> _open(Widget screen) async {
    await Navigator.push(context,
        MaterialPageRoute(builder: (_) => TroikaPageScope(child: screen)));
  }

  Future<void> _openChat() => _open(
        TroikaPage(
          appBar: AppBar(
            title: const Text('Текст'),
            surfaceTintColor: Colors.transparent,
          ),
          body: ChatScreen(
            onOpenCommands: () => _open(const CommandsScreen()),
            onOpenDocuments: () => _open(const LocalDocumentsScreen()),
          ),
        ),
      );

  @override
  void dispose() {
    _assistant?.removeListener(_handleUiAction);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final assistant = context.watch<AssistantService>();
    if (_isWindows && _windowsCompact) {
      return _CompactAssistant(
        assistant: assistant,
        pinned: _windowsPinned,
        hotkeyLabel: _windowsHotkeyLabel(TroikaConfig.windowsHotkey),
        onPin: _togglePinned,
        onExpand: _showCommandCenter,
        onClose: _hideCompact,
        onOpenText: () => _openFromCompact(
          TroikaPage(
            appBar: AppBar(title: const Text('Текст')),
            body: ChatScreen(
              onOpenCommands: () => _open(const CommandsScreen()),
              onOpenDocuments: () => _open(const LocalDocumentsScreen()),
            ),
          ),
        ),
        onOpenFiles: () => _openFromCompact(const FilesHubScreen()),
        onOpenSaved: () => _openFromCompact(const AssistantHubScreen()),
      );
    }
    final wide = MediaQuery.sizeOf(context).width >= 900;
    final connected = TroikaConfig.serverUrl.trim().isNotEmpty;
    final voiceHome = _VoiceHome(
      assistant: assistant,
      onOpenText: _openChat,
      onOpenFiles: () => _open(const FilesScreen()),
      onOpenSaved: () => _open(const AssistantHubScreen()),
    );

    return Scaffold(
      backgroundColor: Theme.of(context).scaffoldBackgroundColor,
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
                  VerticalDivider(
                      width: 1, color: Theme.of(context).dividerColor),
                  Expanded(
                    child: Column(
                      children: [
                        _Header(
                          state: assistant.state,
                          connected: connected,
                          onCompact: _isWindows ? _showCompact : null,
                          onSettings: () => _open(
                            SettingsOverviewScreen(
                              onSignedOut: widget.onSignedOut,
                              onAppearanceChanged: widget.onAppearanceChanged,
                            ),
                          ),
                        ),
                        Expanded(child: voiceHome),
                      ],
                    ),
                  ),
                  VerticalDivider(
                      width: 1, color: Theme.of(context).dividerColor),
                  SizedBox(
                    width: 270,
                    child: _RightRail(
                      open: _open,
                      onCaptureScreen:
                          _isWindows ? _captureScreenForVision : null,
                    ),
                  ),
                ],
              )
            : _mobileTab != 0
                ? switch (_mobileTab) {
                    1 => const AssistantHubScreen(),
                    2 => const FilesHubScreen(),
                    3 => SettingsOverviewScreen(
                        onSignedOut: widget.onSignedOut,
                        onAppearanceChanged: widget.onAppearanceChanged),
                    _ => voiceHome,
                  }
                : Column(
                    children: [
                      _Header(
                        state: assistant.state,
                        connected: connected,
                        onSettings: () => _open(
                          SettingsOverviewScreen(
                              onSignedOut: widget.onSignedOut),
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
              selectedIndex: _isWindows ? 0 : _mobileTab,
              backgroundColor: Theme.of(context).colorScheme.surface,
              indicatorColor:
                  Theme.of(context).colorScheme.primary.withValues(alpha: 0.16),
              onDestinationSelected: (index) {
                setState(() => _mobileTab = index);
              },
              destinations: const [
                NavigationDestination(
                  icon: Icon(Icons.home_outlined),
                  selectedIcon: Icon(Icons.home),
                  label: 'Главная',
                ),
                NavigationDestination(
                  icon: Icon(Icons.checklist_rounded),
                  label: 'Дела',
                ),
                NavigationDestination(
                  icon: Icon(Icons.folder_outlined),
                  label: 'Файлы',
                ),
                NavigationDestination(
                  icon: Icon(Icons.person_outline),
                  label: 'Профиль',
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
  final VoidCallback? onCompact;

  const _Header({
    required this.state,
    required this.connected,
    required this.onSettings,
    this.onCompact,
  });

  @override
  Widget build(BuildContext context) {
    final accent = state == AssistantState.error
        ? TroikaColors.error
        : Theme.of(context).colorScheme.primary;
    return Container(
      height: 62,
      padding: const EdgeInsets.symmetric(horizontal: 20),
      decoration: BoxDecoration(
        border:
            Border(bottom: BorderSide(color: Theme.of(context).dividerColor)),
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
          if (onCompact != null)
            TextButton.icon(
              onPressed: onCompact,
              icon: const Icon(Icons.picture_in_picture_alt_outlined, size: 18),
              label: const Text('Compact'),
            ),
          Text(
            connected ? 'На связи' : 'Локально',
            style: TextStyle(
              color: Theme.of(context).colorScheme.onSurfaceVariant,
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
    final orbState = _voiceOrbState(assistant);
    final label = _voiceStateLabel(assistant, orbState);
    final hint = _voiceStateHint(assistant, orbState);
    return LayoutBuilder(
      builder: (context, constraints) {
        final orbSize = constraints.maxHeight < 650 ? 200.0 : 230.0;
        return SingleChildScrollView(
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
                  Text(
                    'Что сделать?',
                    style: Theme.of(context).textTheme.displaySmall,
                  ),
                  const SizedBox(height: 12),
                  Text(
                    label,
                    key: const ValueKey('voice-state-label'),
                    style: TextStyle(
                      color: _voiceAccent(context, orbState),
                      fontSize: 16,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    hint,
                    key: ValueKey(
                      assistant.liveTranscript.isEmpty
                          ? 'voice-state-hint'
                          : 'voice-live-transcript',
                    ),
                    textAlign: TextAlign.center,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                      fontSize: 14,
                    ),
                  ),
                  const SizedBox(height: 4),
                  _OrbButton(
                    assistant: assistant,
                    orbState: orbState,
                    size: orbSize,
                  ),
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
        );
      },
    );
  }
}

class _OrbButton extends StatelessWidget {
  final AssistantService assistant;
  final VoiceOrbState orbState;
  final double size;

  const _OrbButton({
    required this.assistant,
    required this.orbState,
    required this.size,
  });

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      enabled: assistant.pendingApproval == null,
      label: 'Говорить с Тройкой',
      hint: _voiceStateHint(assistant, orbState),
      child: Tooltip(
        message: _voiceStateHint(assistant, orbState),
        child: InkResponse(
          radius: 116,
          containedInkWell: true,
          highlightShape: BoxShape.circle,
          onTap: assistant.pendingApproval == null
              ? () => _handleOrbTap(assistant)
              : null,
          child: StatusOrb(state: orbState, size: size),
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

VoiceOrbState _voiceOrbState(AssistantService assistant) {
  if (assistant.pendingApproval != null) return VoiceOrbState.approval;
  return switch (assistant.state) {
    AssistantState.idle => assistant.lastResult == null ||
            assistant.lastResult!.kind == AssistantResultKind.answer
        ? VoiceOrbState.idle
        : VoiceOrbState.done,
    AssistantState.wakeDetected ||
    AssistantState.recording =>
      VoiceOrbState.listening,
    AssistantState.processing =>
      assistant.isActing ? VoiceOrbState.acting : VoiceOrbState.thinking,
    AssistantState.speaking => VoiceOrbState.speaking,
    AssistantState.error => VoiceOrbState.error,
  };
}

String _voiceStateLabel(AssistantService assistant, VoiceOrbState state) {
  return switch (state) {
    VoiceOrbState.idle => 'Готова',
    VoiceOrbState.listening => 'Слушаю',
    VoiceOrbState.thinking => 'Разбираюсь…',
    VoiceOrbState.acting => assistant.activityStatus,
    VoiceOrbState.approval => 'Нужно разрешение',
    VoiceOrbState.speaking => 'Отвечаю',
    VoiceOrbState.done => 'Готово',
    VoiceOrbState.error => 'Ошибка',
  };
}

String _voiceStateHint(AssistantService assistant, VoiceOrbState state) {
  if (state == VoiceOrbState.listening && assistant.liveTranscript.isNotEmpty) {
    return '“${_summary(assistant.liveTranscript)}”';
  }
  return switch (state) {
    VoiceOrbState.idle => 'Нажми и скажи, что сделать',
    VoiceOrbState.listening => 'Говори. Нажми ещё раз, чтобы отправить',
    VoiceOrbState.thinking => 'Понимаю задачу',
    VoiceOrbState.acting => 'Можно остановить одним нажатием',
    VoiceOrbState.approval => 'Проверь действие ниже',
    VoiceOrbState.speaking => 'Нажми, чтобы прервать ответ',
    VoiceOrbState.done => 'Результат сохранён ниже',
    VoiceOrbState.error => assistant.errorMessage.isEmpty
        ? 'Нажми, чтобы попробовать снова'
        : assistant.errorMessage,
  };
}

Color _voiceAccent(BuildContext context, VoiceOrbState state) {
  return switch (state) {
    VoiceOrbState.error => TroikaColors.error,
    VoiceOrbState.listening ||
    VoiceOrbState.speaking ||
    VoiceOrbState.done =>
      Theme.of(context).colorScheme.primary,
    _ => Theme.of(context).colorScheme.primary,
  };
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
    final orbState = _voiceOrbState(assistant);
    if ((assistant.state == AssistantState.processing ||
            assistant.state == AssistantState.error) &&
        approval == null) {
      cards.add(
        _HomeCard(
          icon: assistant.state == AssistantState.error
              ? Icons.error_outline
              : Icons.bolt_outlined,
          title: _voiceStateLabel(assistant, orbState),
          body: _voiceStateHint(assistant, orbState),
          accent: assistant.state == AssistantState.error
              ? TroikaColors.error
              : Theme.of(context).colorScheme.primary,
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
    if (cards.isEmpty && assistant.webSources.isEmpty) {
      return const SizedBox.shrink();
    }

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
        WebSourcesView(trace: assistant.webSources),
      ],
    );
  }
}

class _HomeCard extends StatelessWidget {
  final IconData icon;
  final String title;
  final String body;
  final Color? accent;
  final String? actionLabel;
  final VoidCallback? onAction;

  const _HomeCard({
    required this.icon,
    required this.title,
    required this.body,
    this.accent,
    this.actionLabel,
    this.onAction,
  });

  @override
  Widget build(BuildContext context) {
    final accent = this.accent ?? Theme.of(context).colorScheme.primary;
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surface,
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
                  style: TextStyle(
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                    height: 1.35,
                  ),
                ),
                if (actionLabel != null && onAction != null)
                  Align(
                    alignment: Alignment.centerRight,
                    child: FilledButton.icon(
                      onPressed: onAction,
                      icon: const Icon(Icons.arrow_forward_rounded, size: 18),
                      label: Text(actionLabel!),
                    ),
                  ),
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
            label: 'Главная',
            active: true,
          ),
          _NavItem(
            icon: Icons.checklist_rounded,
            label: 'Дела',
            onTap: () => open(const AssistantHubScreen()),
          ),
          _NavItem(
            icon: Icons.folder_outlined,
            label: 'Файлы',
            onTap: () => open(const FilesHubScreen()),
          ),
          _NavItem(
            icon: Icons.history_rounded,
            label: 'История',
            onTap: () => open(const HistoryScreen()),
          ),
          _NavItem(
            icon: Icons.memory_outlined,
            label: 'Память',
            onTap: () => open(const MemoryScreen()),
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
        tileColor: active
            ? Theme.of(context).colorScheme.primary.withValues(alpha: 0.11)
            : null,
        leading: Icon(
          icon,
          color: active
              ? Theme.of(context).colorScheme.primary
              : Theme.of(context).colorScheme.onSurfaceVariant,
        ),
        title: Text(label),
        onTap: onTap,
      ),
    );
  }
}

class _RightRail extends StatelessWidget {
  final Future<void> Function(Widget screen) open;
  final VoidCallback? onCaptureScreen;

  const _RightRail({required this.open, this.onCaptureScreen});

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
        if (onCaptureScreen != null)
          _ActionTile(
            icon: Icons.screenshot_monitor_outlined,
            title: 'Снимок для анализа',
            onTap: onCaptureScreen!,
          ),
      ],
    );
  }
}

class _CompactAssistant extends StatelessWidget {
  final AssistantService assistant;
  final bool pinned;
  final String hotkeyLabel;
  final VoidCallback onPin;
  final VoidCallback onExpand;
  final VoidCallback onClose;
  final VoidCallback onOpenText;
  final VoidCallback onOpenFiles;
  final VoidCallback onOpenSaved;

  const _CompactAssistant({
    required this.assistant,
    required this.pinned,
    required this.hotkeyLabel,
    required this.onPin,
    required this.onExpand,
    required this.onClose,
    required this.onOpenText,
    required this.onOpenFiles,
    required this.onOpenSaved,
  });

  @override
  Widget build(BuildContext context) {
    final orbState = _voiceOrbState(assistant);
    return CallbackShortcuts(
      bindings: {
        const SingleActivator(LogicalKeyboardKey.escape): onClose,
      },
      child: Focus(
        autofocus: true,
        child: Scaffold(
          backgroundColor: Theme.of(context).scaffoldBackgroundColor,
          body: SafeArea(
            child: Column(
              children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 10, 8, 4),
                  child: Row(
                    children: [
                      Container(
                        width: 8,
                        height: 8,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: assistant.state == AssistantState.error
                              ? TroikaColors.error
                              : Theme.of(context).colorScheme.primary,
                        ),
                      ),
                      const SizedBox(width: 10),
                      const Text(
                        'Тройка',
                        style: TextStyle(
                          fontSize: 17,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      const Spacer(),
                      IconButton(
                        tooltip: pinned ? 'Открепить' : 'Поверх окон',
                        onPressed: onPin,
                        icon: Icon(
                          pinned ? Icons.push_pin : Icons.push_pin_outlined,
                        ),
                      ),
                      IconButton(
                        tooltip: 'Command Center',
                        onPressed: onExpand,
                        icon: const Icon(Icons.open_in_full_rounded),
                      ),
                      IconButton(
                        tooltip: 'Закрыть · Esc',
                        onPressed: onClose,
                        icon: const Icon(Icons.close_rounded),
                      ),
                    ],
                  ),
                ),
                const Divider(height: 1),
                Expanded(
                  child: SingleChildScrollView(
                    padding: const EdgeInsets.fromLTRB(20, 18, 20, 12),
                    child: Column(
                      children: [
                        Text(
                          _voiceStateLabel(assistant, orbState),
                          style: TextStyle(
                            color: _voiceAccent(context, orbState),
                            fontSize: 16,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          _voiceStateHint(assistant, orbState),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          textAlign: TextAlign.center,
                          style: TextStyle(
                              color: Theme.of(context)
                                  .colorScheme
                                  .onSurfaceVariant),
                        ),
                        const SizedBox(height: 6),
                        _OrbButton(
                          assistant: assistant,
                          orbState: orbState,
                          size: 150,
                        ),
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
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 8, 16, 14),
                  child: Text(
                    '$hotkeyLabel · повторно — остановить · Esc — скрыть',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                      fontSize: 12,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

String _windowsHotkeyLabel(String preset) => switch (preset) {
      'ctrlShiftSpace' => 'Ctrl + Shift + Space',
      'ctrlAltT' => 'Ctrl + Alt + T',
      _ => 'Ctrl + Alt + Space',
    };

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
        tileColor: Theme.of(context).colorScheme.surface,
        leading: Icon(icon, color: Theme.of(context).colorScheme.primary),
        title: Text(title, style: const TextStyle(fontSize: 14)),
        trailing: const Icon(Icons.chevron_right, size: 18),
        onTap: onTap,
      ),
    );
  }
}
