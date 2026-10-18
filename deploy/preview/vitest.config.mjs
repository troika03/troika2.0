import {defineConfig} from 'vitest/config';
export default defineConfig({root:'/work/project', cacheDir:'/tmp/vite-cache',
  test:{environment:'jsdom', globals:true, watch:false, maxWorkers:1,
    cache:false, fsModuleCache:false, fsModuleCachePath:'/tmp/vitest-modules',
    include:['**/*.{test,spec}.{js,jsx,ts,tsx,mjs,cjs}'],
    reporters:['json'], outputFile:'/tmp/vitest-result.json',
    dangerouslyIgnoreUnhandledErrors:false}});
