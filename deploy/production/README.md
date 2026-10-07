# Troika production runtime

This stack runs the authenticated Troika API, private STT worker and SearXNG. The API
binds only to the host loopback interface. Nginx is the sole public entry point
after a domain and TLS certificate are configured.

Runtime secrets live only in `/srv/troika/data/.env`. For the current stack the
file contains only `OPENROUTER_API_KEY` and `GROQ_API_KEY`. Do not copy a local
development `.env`: it may contain workstation paths and runtime overrides.
Do not commit this file or copy it into an image.

SearXNG is the only enabled search provider in this product profile. Other web
provider plugins are disabled through `plugins.disabled`; their inherited code
remains for compatibility. `SEARXNG_URL` is a non-secret internal service URL
defined in Compose, not in the provider credentials file. SearXNG has no host
port and accepts JSON requests only. Its limiter is disabled because only the
private runtime accesses it; public requests still pass through Troika auth
and API rate limits. SearXNG supplies search snippets, not full-page extraction.
Docker does not persist SearXNG stdout/stderr because upstream error messages
can contain search terms. Container health remains available through Compose.
The product profile also suppresses informational query logging.

Before the first deployment, create its separate secret file on the server:

```bash
sudo python3 - <<'PY'
import os
import secrets
from pathlib import Path
path = Path('/srv/troika/data/searxng.env')
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as stream:
    stream.write('SEARXNG_SECRET=' + secrets.token_hex(32) + '\n')
PY
```

Keep this file outside Git and preserve it during upgrades. The SearXNG image
is pinned by digest. Review and test a new digest before updating it.

Deploy from a clean source tree copied to `/srv/troika/releases/<revision>`:

```bash
docker compose -f deploy/production/compose.yaml build
docker compose -f deploy/production/compose.yaml up -d
docker compose -f deploy/production/compose.yaml ps
curl --fail http://127.0.0.1:8765/health
```

Do not proxy the API publicly over plain HTTP. Add the Nginx HTTPS virtual host
only after DNS points the production domain to the server. Render
`nginx-api.conf.template` by replacing `__TROIKA_API_DOMAIN__` with the API
hostname, install it in `/etc/nginx/sites-available/`, then test Nginx before
reload. The template keeps the container port private and rate-limits public
authentication routes.
