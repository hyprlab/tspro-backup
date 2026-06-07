# TS Pro Backup v1.3.0

**New feature: remote restore.** You can now push a stored backup from this
console straight back into the live TS Pro site it came from — for the day the
site's data gets corrupted, or its admin can't log in.

## What's new

Until now, recovery was one-directional and manual: you'd download a backup,
decrypt it, and re-import it from *inside* the site — useless precisely when
the site is broken or you're locked out of it.

Remote restore flips that around. From a connected site's **full** backups,
click **Remote restore**, paste the site's private key, and confirm. This
server pushes the archive to the site, which decrypts and applies it — no admin
login on the site required. It's out-of-band disaster recovery driven entirely
from here.

The site keeps a timestamped copy of its old data before overwriting, and
clears its own login lockouts so you can sign back in afterwards.

## How to turn it on

It's **off until each site opts in** — a destructive recovery path shouldn't be
enabled silently:

1. Upgrade the connected site to **TS Pro 2.11.0 or later**.
2. On that site: **Settings → Off-site backups →** the target for this server →
   tick **"Allow remote restore"**, set the portal's public URL, and save / test.
3. It registers here automatically. This server's site page then shows it as
   **paired**, and full backups gain a **Remote restore** action.

## Security

Two independent secrets gate every restore, so neither alone is enough:

- a **shared token** the site publishes here (authenticates the push), and
- the operator's **private key**, supplied at restore time, which the site
  uses to decrypt the archive *and* to confirm it matches the key on file.

A stolen token alone can't push a malicious archive. This server stays
zero-knowledge — it only forwards ciphertext; the private key passes through
in memory and is never stored.

## Who should upgrade

Everyone, when convenient — the upgrade is safe and automatic, and remote
restore stays dormant until you enable it per site.

```bash
docker compose pull && docker compose up -d
```

## License

[AGPL-3.0-or-later](LICENSE).
