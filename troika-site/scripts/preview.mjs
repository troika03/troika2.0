import { createServer } from 'node:http';
import { Readable } from 'node:stream';
import { randomBytes } from 'node:crypto';
import { stat } from 'node:fs/promises';
import { databaseBinding } from './sqlite-binding.mjs';
const port = Number(process.env.PORT || 4178);
const env = { DB: databaseBinding(), SESSION_SECRET: randomBytes(48).toString('base64'), PAYMENTS_ENABLED: 'false' };
const server = createServer(async (req,res) => {
  const hasBody = !['GET', 'HEAD'].includes(req.method) &&
    (Number(req.headers['content-length']) > 0 || Boolean(req.headers['transfer-encoding']));
  const request = new Request(`http://127.0.0.1:${port}${req.url}`, {
    method: req.method,
    headers: req.headers,
    ...(hasBody ? { body: Readable.toWeb(req), duplex: 'half' } : {}),
  });
  const modified = (await stat('build/server/index.js')).mtimeMs;
  const { default: worker } = await import(`../build/server/index.js?version=${modified}`);
  const result = await worker.fetch(request,env,{});
  res.writeHead(result.status,Object.fromEntries(result.headers));
  if(result.body) Readable.fromWeb(result.body).pipe(res); else res.end();
});
server.listen(port,'127.0.0.1',()=>console.log(`Local: http://127.0.0.1:${port}`));
