# TS Pro Backup v1.2.0

**A follow-up hardening release** that finishes the privilege-separation work
from the security review and adds a few more defence-in-depth layers.
Upgrading is safe and automatic.

## Highlights

- 👥 **The `user` role is now genuinely limited.** Non-admin operators can
  manage sites and backups (create/edit a site's name + retention, browse and
  delete backups) but **can no longer** rotate a site's API key or encryption
  keypair, delete a site, or change a site's encryption policy. Those actions
  are admin-only — enforced on the server and hidden in the console for
  non-admins.
- 🧩 **Content-Security-Policy** on the console: scripts are restricted to
  same-origin plus the (optional) Cloudflare Turnstile widget, framing is
  forbidden (clickjacking), and forms can only post back to the app.
- 📁 **Transient files stay on the data volume.** Upload staging and at-rest
  decrypt temp files now live under `<DATA_DIR>/tmp` (owner-only) instead of
  shared `/tmp` — so any transient plaintext is on the controlled volume and
  disk usage is accounted honestly.
- ⚙️ **Threaded workers.** gunicorn now runs `gthread` workers, so a couple of
  slow multi-GB transfers can't pin every worker and stall the console.
- 🩹 De-versioned the dev-server `Server` banner.

No new configuration is required, and no environment variables changed.

## Install

```bash
docker pull viibeware/tspro-backup:1.2.0
```

Or with Docker Compose — see the [README](README.md#deploy-with-docker-compose).

## Upgrading

```bash
docker compose pull && docker compose up -d
```

Your `./data` volume is preserved. One thing to know: if you have non-admin
(`user`) operators, they will lose access to key rotation, site deletion, and
per-site encryption-policy controls — these are now admin-only by design. Make
sure at least one **admin** account exists for those tasks (there always is —
the seed account is an admin).

## License

[AGPL-3.0-or-later](LICENSE).
