# TS Pro Backup v1.0.0

**Off-site, zero-knowledge backup storage for [Trusted Servants Pro](https://github.com/viibeware).**

This is the first public release. Deploy TS Pro Backup somewhere separate
from your portal, point each TS Pro site at it, and your backups land here —
end-to-end encrypted, retained on a grandfather-father-son schedule, and
browsable from a web console that matches the TS Pro look.

## Why it exists

A backup that lives next to the thing it's backing up isn't really a backup.
TS Pro Backup is the *receiving* half of an off-site pair: each portal pushes
its archives here over an authenticated HTTP API, and this server is the only
place those archives live off-site.

## Highlights

- 🔑 **Zero-knowledge by default.** Every site gets its own X25519 keypair.
  TS Pro encrypts each archive to the site's **public** key before it leaves
  the portal; the **private** key is shown once at site creation and never
  stored here. The server holds only ciphertext and rejects any upload that
  isn't already encrypted (when `require_e2ee` is on). A full server
  compromise still can't read your backups.
- 🧱 **Encryption at rest.** Optional second layer over the storage volume —
  streaming AES-256-GCM, PBKDF2 (600k iterations). Defense-in-depth for the
  disk, independent of the end-to-end layer above.
- 🗓️ **GFS retention.** Keep N recent days / weeks / months / years, applied
  independently per scope so frontend snapshots never evict whole-site
  backups. An all-zero policy keeps everything.
- 🌐 **Drop-in HTTP API** mirroring TS Pro's `put / list / delete / fetch`
  backup-backend shape, with single-shot **and** chunked uploads for
  multi-GB bundles behind a proxy body cap.
- 🎛️ **Web console** — dashboard, per-site API keys, and a backup browser
  with download / delete, styled to match Trusted Servants Pro.
- 🔐 **Cloudflare Turnstile** on the console login (optional).

## Install

```bash
docker pull viibeware/tspro-backup:1.0.0
```

Or with Docker Compose — see the [README](README.md#deploy-with-docker-compose)
for the full walkthrough.

## ⚠️ Keep your keys

Two secrets, lost, mean **permanently unrecoverable** backups — by design:

- the per-site **private key** (the only thing that decrypts your archives), and
- the **at-rest passphrase** / `data/rest.key`, if you rely on encryption at rest.

Store both in a password manager. This server keeps a copy of neither.

## License

[AGPL-3.0-or-later](LICENSE).
