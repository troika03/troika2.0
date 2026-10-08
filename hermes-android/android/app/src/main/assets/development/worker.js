"use strict";
self.onmessage = async event => {
  const { files, mode } = event.data;
  let output = "";
  const collect = text => { if (output.length < 32000) output += String(text).slice(0, 32000 - output.length) + "\n"; };
  try {
    if (mode.startsWith("python")) {
      importScripts("pyodide/pyodide.js");
      const python = await loadPyodide({ indexURL: "pyodide/", fullStdLib: true, stdout: collect, stderr: collect });
      python.FS.mkdir("/project");
      for (const [path, source] of Object.entries(files)) {
        const parts = path.split("/");
        let parent = "/project";
        for (const part of parts.slice(0, -1)) { parent += "/" + part; python.FS.mkdirTree(parent); }
        python.FS.writeFile("/project/" + path, source);
      }
      python.globals.set("check_mode", mode);
      // Only the supplied project exists in the virtual filesystem. No Android files are mounted.
      const encoded = python.runPython(`
import os, sys, json, unittest, traceback
os.chdir('/project')
sys.path.insert(0, '/project')
sys.dont_write_bytecode = True
code = 0
count = None
try:
    if check_mode == 'python_syntax':
        for folder, _, names in os.walk('.'):
            for name in names:
                if name.endswith('.py'):
                    path = os.path.join(folder, name)
                    with open(path, encoding='utf-8') as file:
                        compile(file.read(), path, 'exec')
        print('Синтаксис Python проверен. Тесты не запускались.')
    elif check_mode == 'python_tests':
        suite = unittest.defaultTestLoader.discover('.', pattern='test_*.py')
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        count = result.testsRun
        code = 0 if result.wasSuccessful() and count else 1
    else:
        raise ValueError('Unsupported check mode')
except BaseException:
    traceback.print_exc()
    code = 1
json.dumps({'exit_code': code, 'no_tests': count == 0})
`);
      const report = JSON.parse(encoded);
      self.postMessage({ ...report, output });
      return;
    }
    const pending = [];
    let testCount = 0;
    let failures = 0;
    const test = (name, callback) => {
      if (typeof callback !== "function") throw new Error("Only test(name, callback) is supported on this device");
      testCount++;
      pending.push(Promise.resolve().then(callback).then(
        () => collect("PASS " + name),
        error => { failures++; collect("FAIL " + name + ": " + error); }));
    };
    const assert = (condition, message = "Assertion failed") => { if (!condition) throw new Error(message); };
    assert.strictEqual = assert.equal = (actual, expected) => assert(Object.is(actual, expected), `${actual} !== ${expected}`);
    const deepEqual = (a, b, seen = new WeakMap()) => {
      if (Object.is(a, b)) return true;
      if (!a || !b || typeof a !== "object" || typeof b !== "object" || Object.getPrototypeOf(a) !== Object.getPrototypeOf(b)) return false;
      if (a instanceof Date) return a.getTime() === b.getTime();
      if (a instanceof RegExp) return a.toString() === b.toString();
      if (a instanceof Map || a instanceof Set) throw new Error("Map/Set comparisons require a PC check");
      if (seen.has(a)) return seen.get(a) === b;
      seen.set(a, b);
      const keys = Object.keys(a);
      return keys.length === Object.keys(b).length && keys.every(key => Object.prototype.hasOwnProperty.call(b, key) && deepEqual(a[key], b[key], seen));
    };
    assert.deepStrictEqual = assert.deepEqual = (actual, expected) => assert(deepEqual(actual, expected), "Values differ");
    assert.ok = assert;
    assert.throws = (callback, expected) => {
      let error; try { callback(); } catch (caught) { error = caught; }
      assert(error !== undefined, "Expected exception");
      if (expected instanceof RegExp) assert(expected.test(String(error)), "Wrong exception");
      else if (typeof expected === "function") assert(error instanceof expected, "Wrong exception type");
      else if (expected !== undefined) throw new Error("Exception object matching requires a PC check");
    };
    const modules = new Map();
    const normalize = path => {
      const parts = [];
      for (const part of path.split("/")) {
        if (part === "." || !part) continue;
        if (part === "..") { if (!parts.length) throw new Error("Module escapes project"); parts.pop(); }
        else parts.push(part);
      }
      return parts.join("/");
    };
    const load = path => {
      path = normalize(path);
      if (!(path in files)) path += ".js";
      if (!(path in files)) throw new Error("Module not found: " + path);
      if (modules.has(path)) return modules.get(path).exports;
      const module = { exports: {} };
      modules.set(path, module);
      const parent = path.split("/").slice(0, -1).join("/");
      const require = name => {
        if (["node:assert/strict", "assert/strict", "assert", "node:assert"].includes(name)) return assert;
        if (["node:test", "test"].includes(name)) return Object.assign(test, { test });
        if (!name.startsWith(".")) throw new Error("Пакет " + name + " недоступен на телефоне. Выбери проверку на ПК.");
        return load(parent + "/" + name);
      };
      new Function("require", "module", "exports", "__filename", "__dirname", files[path])(
        require, module, module.exports, path, parent);
      return module.exports;
    };
    self.console = { log: (...parts) => collect(parts.join(" ")), error: (...parts) => collect(parts.join(" ")), warn: (...parts) => collect(parts.join(" ")) };
    if (mode === "javascript") {
      for (const [path, source] of Object.entries(files)) if (path.endsWith(".js")) new Function(source);
      collect("Синтаксис JavaScript проверен. Тесты не запускались.");
    } else if (mode === "javascript_tests") {
      for (const path of Object.keys(files)) if (/(^|\/)test_[^/]+\.js$|\.test\.js$/.test(path)) load(path);
      await Promise.all(pending);
      collect("Tests: " + testCount + ", failures: " + failures);
    } else throw new Error("Unsupported check mode");
    self.postMessage({ exit_code: failures || mode === "javascript_tests" && !testCount ? 1 : 0, output, no_tests: mode === "javascript_tests" && !testCount });
  } catch (error) {
    collect(error && error.stack || error);
    self.postMessage({ exit_code: 1, output, no_tests: false });
  }
};
