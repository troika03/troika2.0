// Parse project styles as data. Never load project plugins or configuration.
import {transform} from 'esbuild';
import fs from 'node:fs';
let failures = [];
for (const path of process.argv.slice(2)) {
  try {
    const result = await transform(fs.readFileSync(path, 'utf8'), {
      loader: 'css', sourcefile: path, logLevel: 'silent',
    });
    failures.push(...result.warnings.filter(item => item.id === 'css-syntax-error'));
  } catch (error) {
    failures.push(...(error.errors ?? [{text: 'CSS parser failed'}]));
  }
}
for (const item of failures.slice(0, 12)) {
  const where = item.location;
  console.log(`${where?.file ?? 'stylesheet'}:${where?.line ?? 0}:${where?.column ?? 0}: ${item.text}`);
}
process.exitCode = failures.length ? 1 : 0;
