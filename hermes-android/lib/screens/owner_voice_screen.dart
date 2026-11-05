import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:permission_handler/permission_handler.dart';

import '../services/owner_voice_service.dart';
import '../widgets/troika_page.dart';

class OwnerVoiceScreen extends StatefulWidget {
  final OwnerVoiceService? service;
  final Future<bool> Function()? requestMicrophone;

  const OwnerVoiceScreen({super.key, this.service, this.requestMicrophone});

  @override
  State<OwnerVoiceScreen> createState() => _OwnerVoiceScreenState();
}

class _OwnerVoiceScreenState extends State<OwnerVoiceScreen>
    with WidgetsBindingObserver {
  static const _labelStyle = TextStyle(fontFamily: 'Golos Text');
  late final _service = widget.service ?? OwnerVoiceService();
  OwnerVoiceStatus? _status;
  String? _error;
  bool _busy = false;
  bool _recording = false;
  int _generation = 0;

  static const _phrases = [
    'Тройка, помоги мне спланировать завтрашний день и напомни о важных делах вечером.',
    'Тройка, я хочу спокойно обсудить планы на неделю и подготовить всё необходимое для работы.',
    'Тройка, найди интересную тему для разговора и расскажи о ней простыми понятными словами.',
  ];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _run(_service.status);
  }

  Future<void> _run(Future<OwnerVoiceStatus> Function() operation) async {
    final generation = ++_generation;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final status = await operation();
      if (mounted && generation == _generation) {
        setState(() => _status = status);
      }
    } on PlatformException catch (error) {
      if (mounted && generation == _generation) {
        setState(
          () => _error =
              error.message ?? 'Не удалось проверить голос. Повтори запись.',
        );
      }
    } catch (_) {
      if (mounted && generation == _generation) {
        setState(
          () => _error = 'Проверка голоса недоступна. Попробуй ещё раз.',
        );
      }
    } finally {
      if (mounted && generation == _generation) {
        setState(() {
          _busy = false;
          _recording = false;
        });
      }
    }
  }

  Future<void> _enroll() async {
    final generation = _generation + 1;
    await _run(() async {
      final allowed =
          await (widget.requestMicrophone?.call() ?? _requestMicrophone());
      if (!mounted || generation != _generation) {
        return _status ?? const OwnerVoiceStatus();
      }
      final lifecycle = WidgetsBinding.instance.lifecycleState;
      if (lifecycle != null && lifecycle != AppLifecycleState.resumed) {
        throw PlatformException(
          code: 'voice_not_foreground',
          message: 'Вернись в приложение и начни запись заново.',
        );
      }
      if (!allowed) {
        throw PlatformException(
          code: 'microphone_denied',
          message: 'Разреши доступ к микрофону, чтобы зарегистрировать голос.',
        );
      }
      setState(() => _recording = true);
      return _service.enroll();
    });
  }

  Future<bool> _requestMicrophone() async =>
      (await Permission.microphone.request()).isGranted;

  Future<void> _cancel() async {
    ++_generation;
    setState(() {
      _busy = false;
      _recording = false;
    });
    try {
      await _service.cancel();
    } catch (_) {
      // A detached native activity already invalidates its recording callback.
    }
    if (mounted) await _run(_service.status);
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state != AppLifecycleState.resumed && _recording) _cancel();
  }

  @override
  void dispose() {
    ++_generation;
    WidgetsBinding.instance.removeObserver(this);
    if (_recording) _service.cancel().catchError((Object _) {});
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final status = _status;
    return TroikaPage(
      appBar: AppBar(title: const Text('Мой голос', style: _labelStyle)),
      body: Align(
        alignment: Alignment.topCenter,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 640),
          child: ListView(
            padding: const EdgeInsets.fromLTRB(20, 12, 20, 32),
            children: [
              if (status != null && !status.supported)
                const Text(
                  'Проверка голоса недоступна в этой версии приложения.',
                )
              else if (status != null) ...[
                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text(
                    'Отвечать только на мой голос',
                    style: _labelStyle,
                  ),
                  subtitle: Text(
                    status.enrolled
                        ? 'Команды — от четырёх секунд речи.'
                        : 'Сначала запиши три фразы.',
                    style: _labelStyle,
                  ),
                  value: status.enabled,
                  onChanged: !_busy && status.enrolled
                      ? (value) => _run(() => _service.setEnabled(value))
                      : null,
                ),
                if (status.enabled && !status.enrolled) ...[
                  const SizedBox(height: 8),
                  const Text(
                    'Образец повреждён. Голосовой ввод заблокирован. Удали образец и запиши заново.',
                  ),
                ] else if (!status.enrolled) ...[
                  const SizedBox(height: 16),
                  Text(
                    'Фраза ${status.samples + 1} из 3',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  const SizedBox(height: 8),
                  const Text('Прочитай обычным голосом, 5–8 секунд.'),
                  const SizedBox(height: 12),
                  Text(
                    _phrases[status.samples.clamp(0, 2)],
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  const SizedBox(height: 16),
                  FilledButton.icon(
                    onPressed: _busy ? null : _enroll,
                    icon: const Icon(Icons.mic_none),
                    label: Text(
                      _recording ? 'Слушаю…' : 'Записать фразу',
                      style: _labelStyle,
                    ),
                  ),
                ] else ...[
                  const SizedBox(height: 8),
                  const Text('Голос сохранён.'),
                ],
                if (_recording)
                  TextButton(
                    onPressed: _cancel,
                    child: const Text('Отменить запись', style: _labelStyle),
                  ),
                if (status.samples > 0 || status.enrolled || status.enabled)
                  TextButton(
                    onPressed: _busy ? null : () => _run(_service.delete),
                    child: const Text(
                      'Удалить образец голоса',
                      style: _labelStyle,
                    ),
                  ),
                const SizedBox(height: 16),
                const Text('Образец хранится только на этом устройстве.'),
                const ExpansionTile(
                  tilePadding: EdgeInsets.zero,
                  title: Text('О проверке', style: _labelStyle),
                  children: [
                    Padding(
                      padding: EdgeInsets.only(bottom: 16),
                      child: Text(
                        'Образец привязан к твоему аккаунту. Записи регистрации не сохраняются и не отправляются на сервер. '
                        'На другом устройстве нужна новая регистрация. '
                        'При включённом фильтре говори «Тройка» вместе с командой: нужно около четырёх секунд речи. '
                        'Шум может мешать. Запись или копия голоса может пройти проверку; это не замена паролю. '
                        'Текстовый ввод остаётся доступным.',
                      ),
                    ),
                  ],
                ),
              ],
              if (_busy) ...[
                const SizedBox(height: 16),
                const LinearProgressIndicator(),
                const SizedBox(height: 8),
                Text(
                  _recording
                      ? 'Прочитай фразу и сделай паузу.'
                      : 'Подготавливаю…',
                ),
              ],
              if (_error != null) ...[
                const SizedBox(height: 16),
                Text(
                  _error!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
                if (status == null)
                  TextButton(
                    onPressed: _busy ? null : () => _run(_service.status),
                    child: const Text('Повторить', style: _labelStyle),
                  ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
