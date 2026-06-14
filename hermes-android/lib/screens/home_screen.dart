import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../config/hermes_config.dart';
import '../services/assistant_service.dart';
import '../theme/troika_theme.dart';
import '../widgets/status_orb.dart';
import '../widgets/conversation_view.dart';
import '../widgets/text_input_bar.dart';
import 'settings_screen.dart';
import 'history_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  @override
  void initState() {
    super.initState();
    // Первый запуск: сервер ещё не настроен — мягко уводим новичка в Настройки,
    // чтобы он не тыкал в «сломанный» орб без понимания что делать.
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
    final state = assistant.state;
    final isRecording = state == AssistantState.recording;
    final isProcessing = state == AssistantState.processing ||
        state == AssistantState.speaking;
    final accent = TroikaColors.forState(state);

    return Scaffold(
      backgroundColor: TroikaColors.bg,
      body: SafeArea(
        child: Column(
          children: [
            _TopBar(accent: accent),

            // Орб — центр всего
            Expanded(
              flex: 5,
              child: Center(
                child: GestureDetector(
                  behavior: HitTestBehavior.opaque,
                  onTap: () {
                    if (state == AssistantState.idle ||
                        state == AssistantState.error) {
                      assistant.startManualRecording();
                    } else if (isRecording) {
                      assistant.stopRecordingAndProcess();
                    } else if (isProcessing) {
                      assistant.interrupt();
                    }
                  },
                  child: StatusOrb(state: state),
                ),
              ),
            ),

            // Спокойная подпись состояния
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Text(
                TroikaColors.hint(state),
                style: TextStyle(
                  color: state == AssistantState.error
                      ? TroikaColors.error.withOpacity(0.9)
                      : TroikaColors.textMuted,
                  fontSize: 14,
                  letterSpacing: 0.2,
                ),
              ),
            ),

            // Лента диалога
            Expanded(
              flex: 4,
              child: ConversationView(
                userText: assistant.lastUserText,
                hermesText: assistant.lastHermesText,
                errorText: state == AssistantState.error
                    ? assistant.errorMessage
                    : null,
              ),
            ),

            TextInputBar(onSubmit: assistant.sendTextQuery),
            const SizedBox(height: 12),
          ],
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
      padding: const EdgeInsets.only(left: 20, right: 6, top: 10, bottom: 2),
      child: Row(
        children: [
          // Маленький фирменный знак-точка
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
            icon: const Icon(Icons.history_rounded),
            color: TroikaColors.textMuted,
            iconSize: 22,
            onPressed: () => Navigator.push(
              context,
              MaterialPageRoute(builder: (_) => const HistoryScreen()),
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
