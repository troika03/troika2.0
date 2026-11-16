import '../widgets/troika_page.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../config/troika_config.dart';
import '../services/account_service.dart';
import '../services/assistant_service.dart';

class AuthScreen extends StatefulWidget {
  final VoidCallback onAuthenticated;
  final bool startWithSignIn;

  const AuthScreen({
    super.key,
    required this.onAuthenticated,
    this.startWithSignIn = false,
  });

  @override
  State<AuthScreen> createState() => _AuthScreenState();
}

class _AuthScreenState extends State<AuthScreen> {
  final _email = TextEditingController();
  final _password = TextEditingController();
  late final TextEditingController _server;
  final _accounts = AccountService();
  late bool _register;
  bool _busy = false;
  bool _showServer = false;
  bool _showPassword = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _register = !widget.startWithSignIn && !TroikaConfig.onboardingDone;
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
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await TroikaConfig.saveServerUrl(_normalizedServer());
      if (_register) {
        await _accounts.register(email: email, password: password);
      } else {
        await _accounts.login(email: email, password: password);
      }
      if (!mounted) return;
      await context.read<AssistantService>().onAccountAuthenticated();
      if (mounted) widget.onAuthenticated();
    } on AccountException catch (error) {
      if (!mounted) return;
      setState(() {
        if (_register && error.statusCode == 409) {
          _register = false;
          _error = 'Аккаунт с этой почтой уже есть. Нажмите «Войти».';
        } else {
          _error = error.message;
        }
      });
    } catch (_) {
      if (mounted) setState(() => _error = 'Не удалось подключиться.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return TroikaPage(
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
                    TroikaIntro(
                        icon: Icons.waving_hand_outlined,
                        title:
                            _register ? 'Привет, я Тройка' : 'С возвращением',
                        subtitle: _register
                            ? 'Создай бесплатный аккаунт. Разговоры, память и дела будут доступны после входа.'
                            : 'Войди, чтобы вернуться к своим разговорам и делам.'),
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
                      obscureText: !_showPassword,
                      autofillHints: [
                        _register
                            ? AutofillHints.newPassword
                            : AutofillHints.password,
                      ],
                      onSubmitted: (_) => _busy ? null : _submit(),
                      decoration: InputDecoration(
                        labelText: 'Пароль',
                        helperText: 'Минимум 10 символов',
                        suffixIcon: IconButton(
                            tooltip: _showPassword
                                ? 'Скрыть пароль'
                                : 'Показать пароль',
                            onPressed: () =>
                                setState(() => _showPassword = !_showPassword),
                            icon: Icon(_showPassword
                                ? Icons.visibility_off_outlined
                                : Icons.visibility_outlined)),
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
