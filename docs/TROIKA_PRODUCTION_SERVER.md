# Production server baseline

This document records the reproducible operating-system baseline for the
Troika production VPS. It intentionally contains no passwords, private keys,
provider credentials, model credentials, or public client defaults.

## Current baseline

Provisioned on 2026-09-27:

- Ubuntu 22.04 LTS, x86-64, UTC;
- 2 vCPU, approximately 2 GiB RAM, 54 GiB root filesystem;
- approximately 3.7 GiB swap with low swappiness;
- Docker Engine and Docker Compose installed from Docker's official repository;
- Nginx is the only public web entry point;
- automatic Ubuntu security updates enabled;
- persistent system journal limited to 200 MB and 14 days;
- Docker JSON logs rotate at 10 MB with five files;
- filesystem trimming enabled.

The `jammy-proposed` repository supplied by the VPS image is disabled. Only
normal Ubuntu repositories and Docker's official repository may be used for
production packages.

The provider image has unreliable first-attempt DHCP after boot. The
`NetworkManager-wait-online` timeout is set to 120 seconds, and post-reboot
verification confirmed that the lease and SSH access recover without a static
network override. Do not replace the provider network configuration remotely.

## Administrative access

Use the unprivileged `troika-admin` account with a dedicated Ed25519 key. The
account has audited sudo access. Direct root SSH and SSH password
authentication are disabled. X11 and SSH agent forwarding are disabled.

The local workstation has the SSH alias `troika-prod`. Do not commit the host
address or private key. Two approved public keys are installed for the
administrator account. Dokku is not installed or used. Revoking a key requires
removing it from the administrator's `authorized_keys` file.

The production host-key fingerprint observed during provisioning is:

```text
SHA256:HVqlFDK4gfDJ8KnRBE3nApvW3YZA3N4ActMDm/lFTPM
```

Verify this fingerprint through the VPS provider console after any rebuild.
A changed fingerprint must stop deployment until the rebuild or key rotation
is confirmed.

## Network policy

UFW denies inbound traffic by default and allows only:

- TCP 22 for key-only SSH, protected by Fail2ban;
- TCP 80 for ACME and HTTPS redirects;
- TCP 443 for the public API and website.

Fail2ban protects SSH. Product containers must not publish API, STT, preview,
database, object-storage, queue, metrics, or debug ports directly. Nginx must
proxy approved HTTP and WebSocket routes over an internal Docker network.

## Deployment status

The operating-system baseline is configured. No Troika application is public
yet. The legacy `docker-compose.troika.yml` is not a production deployment
manifest because it publishes ports 8642, 8643, and 7800-7900 and uses the old
single-volume runtime. Do not run it on this host.

Production deployment remains blocked until all of the following exist:

1. a production domain whose DNS points to the VPS;
2. TLS certificate issuance and HTTPS/WSS-only routing;
3. a reviewed product-mode image built from the current repository revision;
4. externalized secrets with no values in Git, images, or client builds;
5. private Postgres, object storage, and queue choices;
6. encrypted backup, restore, and deletion-rehearsal procedures;
7. health, readiness, metrics, alerting, rollback, and cost limits.

## Verification

After host changes, verify:

```bash
ssh troika-prod
sudo sshd -T
sudo ufw status verbose
sudo fail2ban-client status sshd
sudo systemctl --failed
sudo systemctl status NetworkManager-wait-online.service
sudo ss -lntup
sudo docker info
sudo docker compose version
sudo nginx -t
```

Expected public listeners are SSH, HTTP, and HTTPS only. Before an application
is deployed, HTTPS may have no listener. Any unexpected public port is a
release blocker.
