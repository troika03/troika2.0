import 'dart:async';
import 'dart:io';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('troika/development');
  Future<Map<String, dynamic>> check(Map<String, String> files, String mode,
          {int timeout = 60000}) async =>
      (await channel.invokeMapMethod<String, dynamic>(
          'check', {'files': files, 'mode': mode, 'timeout_ms': timeout}))!;

  testWidgets(
      'Android offline Python failure, fix, zero tests, timeout and Stop',
      (tester) async {
    if (!Platform.isAndroid) return;
    final sources = {
      'calc.py': 'def add(a,b): return a+b+1\n',
      'test_calc.py':
          'import unittest\nfrom calc import add\nclass Calc(unittest.TestCase):\n def test_add(self): self.assertEqual(add(2,2),4)\n',
    };
    final failed = await check(sources, 'python_tests');
    expect(failed['exit_code'], 1, reason: failed['output']);
    final fixed = await check(
        {...sources, 'calc.py': 'def add(a,b): return a+b\n'}, 'python_tests');
    expect(fixed['exit_code'], 0, reason: fixed['output']);
    final empty = await check({'main.py': 'print(42)'}, 'python_tests');
    expect(empty['no_tests'], true, reason: empty['output']);
    final timeout = await check(
        {'test_hang.py': 'while True: pass'}, 'python_tests',
        timeout: 3000);
    expect(timeout['timed_out'], true);
    final active = check({'test_hang.py': 'while True: pass'}, 'python_tests');
    await Future<void>.delayed(const Duration(seconds: 2));
    await channel.invokeMethod<void>('stop');
    expect((await active)['cancelled'], true);
  });

  testWidgets('Android JavaScript tests and external network denial',
      (tester) async {
    if (!Platform.isAndroid) return;
    final passed = await check({
      'index.js': 'exports.add=(a,b)=>a+b;',
      'test_calc.js':
          'const test=require("node:test");const assert=require("node:assert/strict");test("calc",()=>assert.equal(require("./index").add(2,2),4));',
    }, 'javascript_tests');
    expect(passed['exit_code'], 0, reason: passed['output']);
    final blocked = await check({
      'test_network.js':
          'const test=require("node:test");test("network",async()=>{await fetch("https://example.com");});'
    }, 'javascript_tests');
    expect(blocked['exit_code'], 1, reason: blocked['output']);
  });
}
