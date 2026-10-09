import '../widgets/troika_page.dart';
import 'package:flutter/material.dart';

import '../services/custom_command_store.dart';

class CommandsScreen extends StatefulWidget {
  const CommandsScreen({super.key});

  @override
  State<CommandsScreen> createState() => _CommandsScreenState();
}

class _CommandsScreenState extends State<CommandsScreen> {
  static const _actions = <String, String>{
    'Открыть YouTube': 'открой ютуб',
    'Открыть Telegram': 'открой телеграм',
    'Открыть настройки': 'открой настройки',
    'Включить фонарик': 'включи фонарик',
    'Выключить фонарик': 'выключи фонарик',
    'Назвать время': 'который час',
    'Показать заряд': 'какой заряд',
    'Открыть камеру': 'открой камеру',
    'Открыть календарь': 'открой календарь',
    'Поставить паузу': 'пауза',
    'Следующий трек': 'следующий трек',
    'Показать команды': 'покажи команды',
    'Создать документ': 'создай документ',
    'Создать презентацию': 'создай презентацию',
  };

  List<CustomCommand> _custom = const [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final custom = await CustomCommandStore.load();
    if (mounted) {
      setState(() => _custom = custom);
    }
  }

  Future<void> _addCommand() async {
    final phrase = TextEditingController();
    var action = _actions.values.first;
    final saved = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          scrollable: true,
          backgroundColor: TroikaPalette.of(context).surface,
          title: const Text('Новая команда'),
          content: SizedBox(
            width: 430,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(
                  controller: phrase,
                  autofocus: true,
                  decoration: const InputDecoration(
                    labelText: 'Что сказать',
                    hintText: 'Например: пора работать',
                  ),
                ),
                const SizedBox(height: 16),
                DropdownButtonFormField<String>(
                  initialValue: action,
                  isExpanded: true,
                  decoration: const InputDecoration(labelText: 'Действие'),
                  items: _actions.entries
                      .map((item) => DropdownMenuItem(
                            value: item.value,
                            child: Text(item.key),
                          ))
                      .toList(),
                  onChanged: (value) {
                    if (value != null) setDialogState(() => action = value);
                  },
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('Отмена'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(dialogContext, true),
              child: const Text('Добавить'),
            ),
          ],
        ),
      ),
    );
    final spokenPhrase = phrase.text.trim();
    phrase.dispose();
    if (saved != true || spokenPhrase.isEmpty) return;
    final updated = [
      ..._custom.where((item) => item.phrase != spokenPhrase),
      CustomCommand(phrase: spokenPhrase, action: action),
    ];
    await CustomCommandStore.save(updated);
    await _load();
  }

  Future<void> _remove(CustomCommand command) async {
    await CustomCommandStore.save(
      _custom.where((item) => item.phrase != command.phrase).toList(),
    );
    await _load();
  }

  @override
  Widget build(BuildContext context) {
    return TroikaPage(
      appBar: AppBar(
        title: const Text('Команды'),
        backgroundColor: TroikaPalette.of(context).bg,
        surfaceTintColor: Colors.transparent,
        actions: [
          TextButton.icon(
            onPressed: _addCommand,
            icon: const Icon(Icons.add),
            label: const Text('Добавить'),
          ),
          const SizedBox(width: 8),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(20, 12, 20, 32),
        children: [
          const TroikaIntro(
              icon: Icons.bolt_outlined,
              title: 'Скажи — и готово',
              subtitle:
                  'Команды без интернета. Можно создать свою фразу для привычного действия.'),
          const _CommandGroup(
            title: 'Общение и помощь',
            commands: [
              'Привет · Пока · Спасибо · Как дела',
              'Кто ты · Что ты умеешь · Покажи команды',
              'Какой сегодня день · Посчитай 12 умножить на 4',
            ],
          ),
          const _CommandGroup(
            title: 'Телефон и приложения',
            commands: [
              'Открой YouTube / Telegram / браузер / настройки',
              'Включи фонарик · Выключи фонарик',
              'Позвони · Напиши SMS · Открой камеру · Сделай фото',
              'Поставь таймер / будильник · Проложи маршрут',
            ],
          ),
          const _CommandGroup(
            title: 'Система и медиа',
            commands: [
              'Который час · Какая дата · Какой заряд',
              'Громче · Тише · Без звука',
              'Пауза · Следующий трек · Предыдущий трек',
              'Открой Wi-Fi / Bluetooth / звук / экран',
            ],
          ),
          const _CommandGroup(
            title: 'Компьютер',
            commands: [
              'Открой блокнот / калькулятор / проводник',
              'Открой Word / Excel / PowerPoint',
              'Покажи рабочий стол · Переключи окно · Закрой окно',
              'Обнови страницу · Полный экран',
              'Найди … · Сделай скриншот · Заблокируй компьютер',
            ],
          ),
          const SizedBox(height: 18),
          Row(
            children: [
              const Expanded(child: Text('Мои команды', style: _sectionStyle)),
              TextButton(onPressed: _addCommand, child: const Text('Добавить')),
            ],
          ),
          if (_custom.isEmpty)
            Text(
              'Создай свою фразу для готового безопасного действия.',
              style: TextStyle(color: TroikaPalette.of(context).textMuted),
            )
          else
            ..._custom.map((command) => ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: Text('«${command.phrase}»'),
                  subtitle: Text(command.action),
                  trailing: IconButton(
                    tooltip: 'Удалить',
                    icon: const Icon(Icons.close),
                    onPressed: () => _remove(command),
                  ),
                )),
        ],
      ),
    );
  }
}

const _sectionStyle = TextStyle(
  fontSize: 20,
  fontWeight: FontWeight.w600,
);

class _CommandGroup extends StatelessWidget {
  final String title;
  final List<String> commands;

  const _CommandGroup({required this.title, required this.commands});

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: TroikaPalette.of(context).surface,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: TroikaPalette.of(context).line),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [
            TroikaIcon(icon: Icons.bolt_outlined, size: 40),
            const SizedBox(width: 12),
            Expanded(
                child: Text(title,
                    style: const TextStyle(
                        fontSize: 16, fontWeight: FontWeight.w600)))
          ]),
          const SizedBox(height: 8),
          ...commands.map((command) => Padding(
                padding: const EdgeInsets.only(top: 5),
                child: Text(command,
                    style:
                        TextStyle(color: TroikaPalette.of(context).textMuted)),
              )),
        ],
      ),
    );
  }
}
