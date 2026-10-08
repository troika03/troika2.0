const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const base = path.resolve(__dirname, '../android/app/src/main/assets/development');
const script = fs.readFileSync(path.join(base, 'worker.js'), 'utf8');

async function check(files, mode) {
  return new Promise((resolve, reject) => {
    const sandbox = { console, Promise, Map, Set, WeakMap, Date, RegExp };
    sandbox.self = sandbox;
    sandbox.postMessage = resolve;
    sandbox.importScripts = () => {
      const { loadPyodide } = require(path.join(base, 'pyodide/pyodide.js'));
      sandbox.loadPyodide = options => loadPyodide({ ...options, indexURL: path.join(base, 'pyodide/') });
    };
    vm.createContext(sandbox);
    vm.runInContext(script, sandbox);
    sandbox.onmessage({ data: { files, mode } }).catch(reject);
  });
}

test('JavaScript imports real project code and reports pass/fail/zero tests', async () => {
  const sources = {
    'index.js': 'exports.add = (a,b) => a+b;',
    'test_math.js': 'const test=require("node:test"); const assert=require("node:assert/strict"); const {add}=require("./index"); test("add", ()=>assert.equal(add(2,2),4));',
  };
  assert.equal((await check(sources, 'javascript_tests')).exit_code, 0);
  const failed = await check({ ...sources, 'index.js': 'exports.add=(a,b)=>a+b+1;' }, 'javascript_tests');
  assert.equal(failed.exit_code, 1);
  assert.match(failed.output, /FAIL add/);
  assert.equal((await check({ 'index.js': 'exports.add = (a,b)=>a+b;' }, 'javascript_tests')).no_tests, true);
});

test('unsupported test callback does not become a false pass', async () => {
  const result = await check({ 'test_bad.js': 'require("node:test")("fake", {});' }, 'javascript_tests');
  assert.equal(result.exit_code, 1);
});

test('syntax check does not execute code', async () => {
  const result = await check({ 'index.js': 'throw new Error("must not execute")' }, 'javascript');
  assert.equal(result.exit_code, 0);
});

test('Python WASM runs unittest against actual implementation and reports errors', async () => {
  const sources = {
    'calc.py': 'def add(a,b): return a+b\n',
    'test_calc.py': 'import unittest\nfrom calc import add\nclass Calc(unittest.TestCase):\n def test_add(self): self.assertEqual(add(2,2),4)\n',
  };
  const passed = await check(sources, 'python_tests');
  assert.equal(passed.exit_code, 0, passed.output);
  assert.match(passed.output, /Ran 1 test/);
  const failed = await check({ ...sources, 'calc.py': 'def add(a,b): return a+b+1\n' }, 'python_tests');
  assert.equal(failed.exit_code, 1, failed.output);
  const empty = await check({ 'main.py': 'print(42)' }, 'python_tests');
  assert.equal(empty.no_tests, true, empty.output);
});

test('Python syntax does not execute source', async () => {
  const result = await check({ 'main.py': 'raise RuntimeError("must not execute")' }, 'python_syntax');
  assert.equal(result.exit_code, 0, result.output);
});
