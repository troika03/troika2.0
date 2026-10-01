import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../config/troika_config.dart';
import '../services/account_service.dart';
import '../services/assistant_service.dart';

class AuthScreen extends StatefulWidget {
  final VoidCallback onAuthenticated;

  const AuthScreen({super.key, required this.onAuthenticated});

  @override
  State<AuthScreen> createState() => _AuthScreenState();
}

class _AuthScreenState extends State<AuthScreen> {
  final _email = TextEditingController();
  final _password = TextEditingController();
  late final TextEditingController _server;
  final _accounts = AccountService();
  bool _register = true;
  bool _busy = false;
  bool _showServer = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _server = TextEditingController(text: TroikaConfig.serverUrl);
    _showServer = TroikaConfig.serverUrl.trim().isEmpty;
  }

  String _normalizedServer() {
    var value = _server.text.trim();
    if (value.isEmpty) return '';
    if (!value.startsWith('http://') && !value.startsWith('https://')) {
      value = 'https://$value';
    }
    return value.replaceFirst(RegExp(r'/+$'), '');
  }

  Future<void> _submit() async {
    final email = _email.text.trim();
    final password = _password.text;
    if (!email.contains('@')) {
      setState(() => _error = 'Введи корректную почту.');
      return;
    }
    if (password.length < 10) {
      setState(() => _error = 'Пароль должен содержать минимум 10 символов.');
      return;
    }
    TroikaConfig.serverUrl = _normalizedServer();
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      if (_register) {
        await _accounts.register(email: email, password: password);
      } else {
        await _accounts.login(email: email, password: password);
      }
      if (!mounted) return;
      await context.read<AssistantService>().onAccountAuthenticated();
      if (mounted) widget.onAuthenticated();
    } on AccountException catch (error) {
      if (mounted) setState(() => _error = error.message);
    } catch (_) {
      if (mounted) setState(() => _error = 'Не удалось подключиться.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 440),
              child: AutofillGroup(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text(
                      'Тройка',
                      style:
                          Theme.of(context).textTheme.headlineMedium?.copyWith(
                                fontWeight: FontWeight.bold,
                              ),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      _register
                          ? 'Создай бесплатный аккаунт'
                          : 'Войди в аккаунт',
                      style: Theme.of(context)
                          .textTheme
                          .titleMedium
                          ?.copyWith(color: Colors.white70),
                    ),
                    const SizedBox(height: 8),
                    const Text(
                      'Скажи, что нужно сделать. Тройка выполнит задачу, '
                      'сохранит результат и запомнит полезный контекст.',
                    ),
                    const SizedBox(height: 8),
                    const Text(
                      'Например: разобрать задание, подготовить отчёт, '
                      'помочь с кодом или напомнить о деле.',
                      style: TextStyle(color: Colors.white60),
                    ),
                    const SizedBox(height: 24),
                    TextField(
                      controller: _email,
                      enabled: !_busy,
                      keyboardType: TextInputType.emailAddress,
                      autofillHints: const [AutofillHints.email],
                      decoration: const InputDecoration(labelText: 'Почта'),
                    ),
                    const SizedBox(height: 12),
                    TextField(
                      controller: _password,
                      enabled: !_busy,
                      obscureText: true,
                      autofillHints: [
                        _register
                            ? AutofillHints.newPassword
                            : AutofillHints.password,
                      ],
                      onSubmitted: (_) => _busy ? null : _submit(),
                      decoration: const InputDecoration(
                        labelText: 'Пароль',
                        helperText: 'Минимум 10 символов',
                      ),
                    ),
                    const SizedBox(height: 8),
                    if (TroikaConfig.developerDiagnosticsEnabled)
                      TextButton.icon(
                        onPressed: _busy
                            ? null
                            : () => setState(() => _showServer = !_showServer),
                        icon: const Icon(Icons.settings_outlined),
                        label: const Text('Адрес тестового сервера'),
                      ),
                    if (_showServer)
                      TextField(
                        controller: _server,
                        enabled: !_busy,
                        keyboardType: TextInputType.url,
                        decoration: const InputDecoration(
                          labelText: 'https://api.example.ru',
                        ),
                      ),
                    if (_error != null) ...[
                      const SizedBox(height: 12),
                      Text(_error!,
                          style: const TextStyle(color: Colors.redAccent)),
                    ],
                    const SizedBox(height: 20),
                    FilledButton(
                      onPressed: _busy ? null : _submit,
                      child: Padding(
                        padding: const EdgeInsets.symmetric(vertical: 14),
                        child: Text(
                          _busy
                              ? 'Подключение…'
                              : (_register ? 'Зарегистрироваться' : 'Войти'),
                        ),
                      ),
                    ),
                    const SizedBox(height: 8),
                    TextButton(
                      onPressed: _busy
                          ? null
                          : () => setState(() {
                                _register = !_register;
                                _error = null;
                              }),
                      child: Text(
                        _register
                            ? 'Уже есть аккаунт? Войти'
                            : 'Нет аккаунта? Зарегистрироваться',
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    _server.dispose();
    super.dispose();
  }
}
