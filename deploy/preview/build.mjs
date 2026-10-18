// Trusted build recipe. Project npm scripts and configuration are never executed.
import {build} from 'esbuild';
import fs from 'node:fs';
const entry = process.argv[2];
await build({entryPoints:[entry], absWorkingDir:'/work/project',
  outdir:'/work/project/.preview', entryNames:'app', bundle:true,
  format:'esm', platform:'browser', jsx:'automatic',
  define:{'process.env.NODE_ENV':'"production"'},
  loader:{'.svg':'dataurl'}, logLevel:'warning'});
