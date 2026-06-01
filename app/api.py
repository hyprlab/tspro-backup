# SPDX-License-Identifier: AGPL-3.0-or-later
"""HTTP API consumed by TS Pro instances.

This is the off-site destination's wire protocol. It deliberately mirrors
the ``put / list / delete / fetch`` shape of TS Pro's existing backup
backends (``app/backup_backends.py``) so adding a "TS Pro Backup" backend
to TS Pro is a thin HTTP client:

    GET    /api/v1/ping                      auth check + server capabilities
    POST   /api/v1/backups                   upload one archive  (put)
    GET    /api/v1/backups                   list this site's archives (list)
    GET    /api/v1/backups/<id>              one archive's metadata
    GET    /api/v1/backups/<id>/download     download bytes  (fetch)
    DELETE /api/v1/backups/<id>              delete one archive (delete)

Authentication: every request carries the site's API key as either
``Authorization: Bearer <key>`` or ``X-API-Key: <key>``. Retention is
enforced server-side after each upload, so the client never has to prune.
"""
import os
import re
import shutil
import tempfile
import time
from datetime import datetime
from functools import wraps

from flask import (Blueprint, current_app, g, jsonify, request, send_file)

from .models import (SCOPE_FULL, SCOPES, Backup, Setting, Site, db)
from . import pubkey, restenc, storage

bp = Blueprint("api", __name__, url_prefix="/api/v1")

# Chunked upload: clients behind a body-size-limited proxy (e.g.
# Cloudflare's 100 MiB cap) slice the encrypted archive into parts, POST
# each to /backups/chunk, then POST /backups/finalize to reassemble +
# ingest. We advertise this in /ping; small uploads still use the
# single-shot /backups route.
CHUNK_MAX_MB = int(os.environ.get("TSPB_CHUNK_MB", "90"))
_UPLOAD_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _safe_upload_id(s):
    return bool(s and _UPLOAD_ID_RE.match(s))


def _chunk_staging_dir(site_id, upload_id):
    """Per-site, per-upload staging dir for incoming chunks. Scoping by
    site id keeps one site's API key from touching another's chunks."""
    root = os.path.join(current_app.config["DATA_DIR"], "upload-chunks",
                        f"site-{site_id}", upload_id)
    os.makedirs(root, exist_ok=True)
    return root


def _cleanup_stale_chunks(max_age_seconds=24 * 60 * 60):
    """Drop abandoned chunk dirs (client died mid-upload) so they don't
    pile up. Best-effort; never raises."""
    cutoff = time.time() - max_age_seconds
    base = os.path.join(current_app.config["DATA_DIR"], "upload-chunks")
    try:
        for site_dir in os.listdir(base):
            sp = os.path.join(base, site_dir)
            for name in os.listdir(sp):
                d = os.path.join(sp, name)
                try:
                    if os.path.getmtime(d) < cutoff:
                        shutil.rmtree(d, ignore_errors=True)
                except OSError:
                    pass
    except OSError:
        pass


def _e2ee_gate_error(site, path):
    """Apply the end-to-end-encryption upload gate to the file at
    ``path``. Returns a user-facing error string to reject with, or None
    if the upload may proceed. Shared by single-shot + chunked uploads."""
    if not site.effective_require_e2ee(Setting.get()):
        return None
    with open(path, "rb") as fh:
        head = fh.read(8)
    if site.e2ee_public_key:
        if pubkey.head_is_e2ee(head):
            return None
        return ("end-to-end encryption is required: upload the archive encrypted "
                "to this site's public key (TSPEPK01). Configure the TS Pro Backup "
                "target with this site's key so the server only ever receives "
                "ciphertext it cannot read.")
    if restenc.head_is_encrypted(head):
        return None
    return ("end-to-end encryption is required: this archive was not encrypted "
            "before upload. Enable archive encryption in the TS Pro backup "
            "target so the server only ever receives ciphertext.")


def _extract_key():
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (request.headers.get("X-API-Key") or "").strip()


def require_site(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        site = Site.authenticate(_extract_key())
        if site is None:
            return jsonify(ok=False, error="invalid or missing API key"), 401
        site.last_seen_at = datetime.utcnow()
        site.last_seen_ip = request.remote_addr
        db.session.commit()
        g.site = site
        return fn(*args, **kwargs)
    return wrapper


def _backup_json(b: Backup):
    return {
        "id": b.id,
        "scope": b.scope,
        "name": b.original_name,
        "size": b.size_bytes,
        "stored_size": b.stored_bytes,
        "sha256": b.sha256,
        "encrypted_at_rest": b.encrypted_at_rest,
        "client_encrypted": b.client_encrypted,
        "note": b.note,
        "created_at": b.created_at.isoformat() + "Z" if b.created_at else None,
    }


@bp.route("/ping")
@require_site
def ping():
    site = g.site
    settings = Setting.get()
    return jsonify(
        ok=True,
        service="tspro-backup",
        version=current_app.config.get("VERSION", "1.0.0"),
        site={"id": site.id, "name": site.name},
        scopes=list(SCOPES),
        # E2EE capability: when true the client MUST encrypt the archive
        # to this site's public key (TSPEPK01) before uploading — the
        # server rejects plaintext and never holds the private key.
        require_e2ee=site.effective_require_e2ee(settings),
        # Recipient public key the client encrypts each backup to, and the
        # envelope it should produce. Absent only for legacy sites that
        # predate keypairs (rotate the keypair in the console to mint one).
        e2ee_alg="TSPEPK01",
        e2ee_public_key=site.e2ee_public_key,
        encrypt_at_rest=site.effective_encrypt_at_rest(settings),
        retention=site.retention(settings),
        # Chunked/resumable upload support, so clients behind a body-size-
        # limited proxy can split large archives. max_chunk_mb is the
        # largest part the client should send per request.
        chunked_upload=True,
        max_chunk_mb=CHUNK_MAX_MB,
    )


@bp.route("/backups", methods=["POST"])
@require_site
def upload():
    site = g.site
    scope = (request.form.get("scope") or SCOPE_FULL).strip()
    if scope not in SCOPES:
        return jsonify(ok=False, error=f"unknown scope {scope!r}; expected one of {list(SCOPES)}"), 400

    f = request.files.get("file")
    if f is None or not f.filename:
        return jsonify(ok=False, error="missing 'file' part"), 400

    note = (request.form.get("note") or "").strip() or None
    original_name = os.path.basename(f.filename)

    tmp = tempfile.NamedTemporaryFile(prefix="tspb-up-", suffix=".bin", delete=False)
    try:
        f.save(tmp.name)
        tmp.close()

        # End-to-end encryption gate: refuse anything that isn't already
        # ciphertext we can't read (see _e2ee_gate_error).
        why = _e2ee_gate_error(g.site, tmp.name)
        if why:
            return jsonify(ok=False, error=why), 422

        backup = storage.ingest(site, scope, tmp.name, original_name, note=note)
    except Exception as e:  # noqa: BLE001
        current_app.logger.error("upload ingest failed for site=%s: %s", site.id, e)
        return jsonify(ok=False, error="failed to store backup"), 500
    finally:
        try:
            os.remove(tmp.name)
        except OSError:
            pass

    return jsonify(ok=True, backup=_backup_json(backup)), 201


@bp.route("/backups/chunk", methods=["POST"])
@require_site
def upload_chunk():
    """Receive one chunk of a multi-part upload. The client slices the
    encrypted archive into parts (each under the fronting proxy's body
    limit) and POSTs them keyed by a client-generated ``upload_id``.
    Chunks land at ``upload-chunks/site-<id>/<upload_id>/<index:08d>.bin``
    so finalize can concat them in order."""
    upload_id = (request.form.get("upload_id") or "").strip().lower()
    if not _safe_upload_id(upload_id):
        return jsonify(ok=False, error="invalid upload_id (must be a UUID)"), 400
    try:
        chunk_index = int(request.form.get("chunk_index", ""))
        total_chunks = int(request.form.get("total_chunks", ""))
    except ValueError:
        return jsonify(ok=False, error="bad chunk metadata"), 400
    if chunk_index < 0 or total_chunks < 1 or chunk_index >= total_chunks:
        return jsonify(ok=False, error="chunk index out of range"), 400
    chunk = request.files.get("chunk")
    if chunk is None:
        return jsonify(ok=False, error="missing 'chunk' part"), 400

    _cleanup_stale_chunks()
    staging = _chunk_staging_dir(g.site.id, upload_id)
    chunk.save(os.path.join(staging, f"{chunk_index:08d}.bin"))
    return jsonify(ok=True, upload_id=upload_id, chunk_index=chunk_index,
                   total_chunks=total_chunks)


@bp.route("/backups/finalize", methods=["POST"])
@require_site
def upload_finalize():
    """Reassemble the chunks under ``upload_id`` into one archive, run the
    same E2EE gate + ingest as the single-shot route, then clean up the
    staging dir. Returns the stored backup, identical to /backups."""
    site = g.site
    scope = (request.form.get("scope") or SCOPE_FULL).strip()
    if scope not in SCOPES:
        return jsonify(ok=False, error=f"unknown scope {scope!r}; expected one of {list(SCOPES)}"), 400
    upload_id = (request.form.get("upload_id") or "").strip().lower()
    if not _safe_upload_id(upload_id):
        return jsonify(ok=False, error="invalid upload_id (must be a UUID)"), 400

    note = (request.form.get("note") or "").strip() or None
    original_name = os.path.basename((request.form.get("filename") or "backup.bin").strip()) or "backup.bin"

    staging = os.path.join(current_app.config["DATA_DIR"], "upload-chunks",
                          f"site-{site.id}", upload_id)
    if not os.path.isdir(staging):
        return jsonify(ok=False, error="upload session not found — re-upload the chunks"), 404
    chunks = sorted(n for n in os.listdir(staging) if n.endswith(".bin"))
    try:
        expected = int(request.form.get("total_chunks", "0"))
    except ValueError:
        expected = 0
    if expected and len(chunks) != expected:
        return jsonify(ok=False, error=(f"upload incomplete — expected {expected} chunks "
                                        f"but {len(chunks)} arrived; retry")), 409

    tmp = tempfile.NamedTemporaryFile(prefix="tspb-up-", suffix=".bin", delete=False)
    try:
        with open(tmp.name, "wb") as out:
            for name in chunks:
                with open(os.path.join(staging, name), "rb") as src:
                    while True:
                        block = src.read(8 * 1024 * 1024)
                        if not block:
                            break
                        out.write(block)
        tmp.close()

        why = _e2ee_gate_error(site, tmp.name)
        if why:
            return jsonify(ok=False, error=why), 422

        backup = storage.ingest(site, scope, tmp.name, original_name, note=note)
    except Exception as e:  # noqa: BLE001
        current_app.logger.error("finalize ingest failed for site=%s: %s", site.id, e)
        return jsonify(ok=False, error="failed to store backup"), 500
    finally:
        try: os.remove(tmp.name)
        except OSError: pass
        shutil.rmtree(staging, ignore_errors=True)

    return jsonify(ok=True, backup=_backup_json(backup)), 201


@bp.route("/backups")
@require_site
def list_backups():
    site = g.site
    q = Backup.query.filter_by(site_id=site.id)
    scope = request.args.get("scope")
    if scope:
        if scope not in SCOPES:
            return jsonify(ok=False, error=f"unknown scope {scope!r}"), 400
        q = q.filter_by(scope=scope)
    rows = q.order_by(Backup.created_at.desc()).all()
    return jsonify(ok=True, count=len(rows), backups=[_backup_json(b) for b in rows])


@bp.route("/backups/<int:backup_id>")
@require_site
def get_backup(backup_id):
    b = Backup.query.filter_by(id=backup_id, site_id=g.site.id).first()
    if b is None:
        return jsonify(ok=False, error="not found"), 404
    return jsonify(ok=True, backup=_backup_json(b))


@bp.route("/backups/<int:backup_id>/download")
@require_site
def download_backup(backup_id):
    b = Backup.query.filter_by(id=backup_id, site_id=g.site.id).first()
    if b is None:
        return jsonify(ok=False, error="not found"), 404
    app = current_app._get_current_object()
    try:
        path, is_temp = storage.open_for_download(app, b)
    except Exception as e:  # noqa: BLE001
        current_app.logger.error("api download failed for backup %s: %s", backup_id, e)
        return jsonify(ok=False, error="failed to read backup"), 500
    resp = send_file(path, as_attachment=True, download_name=b.original_name)
    if is_temp:
        @resp.call_on_close
        def _cleanup():
            try:
                os.remove(path)
            except OSError:
                pass
    return resp


@bp.route("/backups/<int:backup_id>", methods=["DELETE"])
@require_site
def delete_backup(backup_id):
    b = Backup.query.filter_by(id=backup_id, site_id=g.site.id).first()
    if b is None:
        return jsonify(ok=False, error="not found"), 404
    app = current_app._get_current_object()
    storage.delete_blob(app, b)
    db.session.delete(b)
    db.session.commit()
    return jsonify(ok=True, deleted=backup_id)
