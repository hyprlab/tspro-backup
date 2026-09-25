# API

The `/api/v1` protocol a TS Pro site uses to talk to this server. It is
shaped like TS Pro's other backup targets (`put / list / delete / fetch`), so
the TS Pro side is a thin client.

## Authentication

Every request carries the site's API key, as `Authorization: Bearer <key>` or
`X-API-Key: <key>`. The key identifies the site; each site sees only its own
backups. The API is stateless and has no CSRF check.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/ping` | Auth check and capabilities: scopes, retention, encryption at rest, `require_e2ee`, `e2ee_alg`, `e2ee_public_key`, `remote_restore`. |
| `POST` | `/api/v1/register` | The site publishes its public base URL (`callback_url`), a `restore_token` and `restore_enabled`, for remote restore. Idempotent. |
| `POST` | `/api/v1/backups` | Single-shot upload: multipart `file`, `scope` (`full` or `frontend`), optional `note`. |
| `POST` | `/api/v1/backups/chunk` | One part of a chunked upload: `upload_id` (a client UUID), `chunk_index`, `total_chunks`, `chunk`. |
| `POST` | `/api/v1/backups/finalize` | Reassemble the chunks and store them: `upload_id`, `scope`, `filename`, `total_chunks`, optional `note`. |
| `GET` | `/api/v1/backups` | This site's backups, optionally `?scope=`. |
| `GET` | `/api/v1/backups/<id>` | One backup's metadata. |
| `GET` | `/api/v1/backups/<id>/download` | The original bytes, with the at-rest layer removed. |
| `DELETE` | `/api/v1/backups/<id>` | Delete one backup. |

Use the chunked pair for archives larger than a reverse proxy's request body
limit. Uploads are checked against free disk space and any site quota before
they are accepted.

When the site requires end-to-end encryption and has a key, an upload that
is not a `TSPEPK01` envelope is refused. See
[ARCHITECTURE.md](ARCHITECTURE.md#encryption).

## Example

```bash
curl -H "Authorization: Bearer tspb_XXXX" \
     -F scope=full -F file=@tsp-export-20260531-030000.zip \
     https://backup.example.org/api/v1/backups
```
