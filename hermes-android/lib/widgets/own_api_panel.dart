import 'package:flutter/material.dart';
import '../config/troika_config.dart';
import '../services/own_api_service.dart';
import '../services/troika_api_service.dart';

class OwnApiPanel extends StatefulWidget {
  const OwnApiPanel({super.key});
  @override
  State<OwnApiPanel> createState() => _OwnApiPanelState();
}

class _OwnApiPanelState extends State<OwnApiPanel> {
  final _model = TextEditingController();
  final _key = TextEditingController();
  String _provider = 'openrouter';
  String? _message;
  bool _busy = false;
  @override
  void dispose() { _model.dispose(); _key.dispose(); super.dispose(); }
  Future<void> _apply(bool connect) async {
    setState(() => _busy = true);
    try {
      if (connect) {
        if (!(await TroikaApiService().getSubscription()).byokEnabled) {
          throw StateError('Личный API не поддерживается этим сервером.');
        }
        await OwnApiService.connect(TroikaConfig.accountEmail, _provider, _model.text.trim(), _key.text.trim());
      } else { await OwnApiService.disconnect(); }
      _key.clear();
      if (mounted) setState(() => _message = connect ? 'Подключён личный API. Модель не расходует токены подписки.' : 'Используется ключ Тройки. Модель расходует токены подписки.');
    } catch (_) {
      if (mounted) setState(() => _message = 'Проверь поля и обнови приложение. Подключение не изменено.');
    } finally { if (mounted) setState(() => _busy = false); }
  }
  @override
  Widget build(BuildContext context) => ExpansionTile(
    title: const Text('Свой API-ключ'),
    childrenPadding: const EdgeInsets.symmetric(horizontal: 12),
    children: [
      const Text('Личная модель не расходует токены подписки. Её счета оплачиваются провайдеру. Голос сервиса учитывается отдельно. Ключ хранится в памяти; после перезапуска введи его снова. На ключ Тройки автоматически не переключаемся.'),
      DropdownButtonFormField<String>(initialValue: _provider,
        items: const [DropdownMenuItem(value: 'openrouter', child: Text('OpenRouter')), DropdownMenuItem(value: 'openai', child: Text('OpenAI'))],
        onChanged: (v) { if (v != null) setState(() => _provider = v); }),
      TextField(controller: _model, decoration: const InputDecoration(labelText: 'ID модели')),
      TextField(controller: _key, obscureText: true, autocorrect: false, enableSuggestions: false,
        decoration: const InputDecoration(labelText: 'Личный API-ключ')),
      if (_message != null) Text(_message!),
      TextButton(onPressed: _busy ? null : () => _apply(true), child: const Text('Подключить свой ключ')),
      TextButton(onPressed: _busy ? null : () => _apply(false), child: const Text('Использовать ключ Тройки')),
    ],
  );
}
