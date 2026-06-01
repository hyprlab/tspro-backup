# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fernet symmetric encryption for DB-stored secrets.

Mirrors TS Pro's ``app/crypto.py``. Used to encrypt the Cloudflare
Turnstile secret key (and any other reversible secret) at rest in the
SQLite DB. The key is read from ``TSPB_FERNET_KEY`` if set, otherwise a
key file (``secret.key``) is generated once in the data directory and
reused on every boot. Losing that key (or rotating ``TSPB_FERNET_KEY``)
makes previously-stored secrets unreadable — re-enter them to recover.
"""
import os
from cryptography.fernet import Fernet
from flask import current_app


def init_fernet(app):
    key = os.environ.get("TSPB_FERNET_KEY")
    if not key:
        data_dir = app.config["DATA_DIR"]
        path = os.path.join(data_dir, "secret.key")
        if os.path.exists(path):
            with open(path, "rb") as f:
                key = f.read().decode()
        else:
            key = Fernet.generate_key().decode()
            with open(path, "wb") as f:
                f.write(key.encode())
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
    app.config["FERNET"] = Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(value: str) -> bytes:
    return current_app.config["FERNET"].encrypt((value or "").encode())


def decrypt(token: bytes) -> str:
    if not token:
        return ""
    try:
        return current_app.config["FERNET"].decrypt(token).decode()
    except Exception:
        try:
            current_app.logger.warning(
                "Fernet decrypt failed — encrypted column unreadable. "
                "Most likely cause: TSPB_FERNET_KEY or secret.key was "
                "rotated after this value was stored. Re-enter the affected "
                "secret to re-encrypt under the current key."
            )
        except Exception:
            pass
        return ""
