# TS Pro Backup v1.2.1

**Hotfix.** Fixes a regression that broke console sign-in over HTTPS.

## The bug

On a TLS deployment (the recommended production setup), logging in — and every
other console form — failed with:

```
400 Bad Request
The referrer header is missing.
```

The `Referrer-Policy: no-referrer` header added in 1.1.0 told browsers never to
send the `Referer` header, but Flask-WTF's CSRF protection performs a strict
referrer check over HTTPS and rejects a form POST whose `Referer` is missing.

## The fix

The policy is now `Referrer-Policy: same-origin`: the `Referer` is sent on
same-origin requests (so CSRF passes) and still withheld from external sites.

## Who should upgrade

**Anyone running 1.1.0 or 1.2.0 behind HTTPS** — sign-in is broken on those
versions. Upgrade with:

```bash
docker compose pull && docker compose up -d
```

No data or configuration changes.

## License

[AGPL-3.0-or-later](LICENSE).
