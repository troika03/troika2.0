# Troika production runtime

This stack runs the authenticated Troika API and private STT worker. The API
binds only to the host loopback interface. Nginx is the sole public entry point
after a domain and TLS certificate are configured.

Runtime secrets live only in `/srv/troika/data/.env`. For the current stack the
file contains only `OPENROUTER_API_KEY` and `GROQ_API_KEY`. Do not copy a local
development `.env`: it may contain workstation paths and runtime overrides.
Do not commit this file or copy it into an image.

Deploy from a clean source tree copied to `/srv/troika/releases/<revision>`:

```bash
docker compose -f deploy/production/compose.yaml build
docker compose -f deploy/production/compose.yaml up -d
docker compose -f deploy/production/compose.yaml ps
curl --fail http://127.0.0.1:8765/health
```

Do not proxy the API publicly over plain HTTP. Add the Nginx HTTPS virtual host
only after DNS points the production domain to the server.
