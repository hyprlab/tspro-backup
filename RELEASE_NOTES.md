# TS Pro Backup v1.1.0

**A security-hardening release.**

After a full security review of the whole app, this release adds brute-force
protection to the console login and closes a range of authentication,
encryption-integrity, and denial-of-service gaps. Upgrading is safe and
automatic — see the one-time effects under [Upgrading](#upgrading).

## Highlights

- 🔒 **Login lockout.** Failed console sign-ins are now rate-limited with a
  sliding window (per username **and** per IP) that survives restarts and
  multiple workers — so the operator password can't be brute-forced. Tunable
  via `TSPB_LOGIN_MAX_FAILURES` / `TSPB_LOGIN_WINDOW_MINUTES`.
- 🪪 **Forced first-login password change.** Any account still on the default
  `admin` password is walked through a one-time change wizard before anything
  else is reachable — no more standing `admin/admin`.
- 🔑 **No usable default signing key.** With `TSPB_SECRET_KEY` unset, the
  server now generates and persists a random key instead of a shipped
  constant, closing an admin-session-forgery path on non-compose deployments.
  Changing a password also invalidates that account's other sessions.
- 🧬 **Stronger E2EE gate.** The upload gate validates the full `TSPEPK01`
  envelope structure (not just an 8-byte magic prefix), rejects E2EE-required
  uploads from keyless sites, and records the recipient-key fingerprint per
  backup. The zero-knowledge guarantee is now described honestly: the server
  validates *format*, because it holds no private key to verify ciphertext.
- 🧱 **Upload DoS caps.** Chunked uploads enforce per-chunk, total-count,
  cumulative-size, and free-disk limits, with an optional per-site quota
  (`TSPB_SITE_QUOTA_MB`); `total_chunks` is mandatory and chunks must be
  contiguous, so a partial upload can't become a silently truncated backup.
- 🛡️ **Hardened runtime.** The container runs as a non-root user; responses
  carry `X-Frame-Options` / `X-Content-Type-Options` / `Referrer-Policy` /
  HSTS; `remember-me` cookies get the same flags as the session cookie; the DB
  and blobs are `0600`; `/logout` is POST-only; and the Werkzeug debugger is
  split onto its own `TSPB_FLASK_DEBUG` flag.
- ⬆️ **Dependencies.** Werkzeug → 3.0.6 (CVE-2024-49767), requests → 2.32.4.
- 🐞 **Fixed** a fresh-boot crash race (two workers seeding the database at
  once) and enabled SQLite foreign-key cascade so deleting a site cleans up
  its backups instead of orphaning them.

## Install

```bash
docker pull viibeware/tspro-backup:1.1.0
```

Or with Docker Compose — see the [README](README.md#deploy-with-docker-compose).

## Upgrading

```bash
docker compose pull && docker compose up -d
```

Your `./data` volume is preserved and schema changes apply automatically.
Three one-time effects:

1. **All current console sessions are invalidated once** (the session-token
   format changed) — just sign in again.
2. **Any admin still using the `admin` password** is sent through the forced
   change wizard on next sign-in.
3. **A site that has E2EE required but no encryption key** must have its
   keypair rotated in the console before it can accept uploads again.

If your container port is reachable directly (not solely through a trusted
reverse proxy that overwrites `X-Forwarded-For`), set `TSPB_TRUST_PROXY=0` so
the login lockout keys on the real client IP.

## ⚠️ Keep your keys

Two secrets, lost, mean **permanently unrecoverable** backups — by design:
the per-site **private key**, and the **at-rest passphrase** / `data/rest.key`
if you rely on encryption at rest. This server keeps a copy of neither.

## License

[AGPL-3.0-or-later](LICENSE).
