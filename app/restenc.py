# SPDX-License-Identifier: AGPL-3.0-or-later
"""Streaming AES-256-GCM encryption for backups stored at rest.

Shares the on-disk format with TS Pro's ``app/bundle_crypto.py`` so the
two codebases speak the same envelope. When "encrypt at rest" is on, the
server wraps every stored archive with this before it touches disk and
unwraps it on download, so a stolen disk / volume snapshot yields only
ciphertext. This is independent of (and composes with) any client-side
encryption TS Pro may already have applied to the bundle — we never look
inside, we just add a layer.

File format (binary, no trailing newline)::

    [magic 8 bytes 'TSPENC01']
    [salt  16 bytes]
    [nonce 12 bytes]
    [ciphertext stream — variable]
    [auth tag 16 bytes]

PBKDF2-HMAC-SHA256 with 600_000 iterations derives a 32-byte AES key
from the rest passphrase + a fresh random salt per file. Both encrypt
and decrypt walk the input in 1 MiB blocks, so a multi-GB archive costs
O(1) memory.
"""
from __future__ import annotations

import os
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


MAGIC = b"TSPENC01"
_SALT_LEN = 16
_NONCE_LEN = 12
_TAG_LEN = 16
_PBKDF2_ITERS = 600_000
_BLOCK = 1024 * 1024  # 1 MiB per encrypt / decrypt cycle


class RestDecryptError(Exception):
    """Raised when at-rest decryption fails — wrong passphrase, a
    truncated / corrupted blob, or bad magic bytes."""


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_PBKDF2_ITERS,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def encrypt_file(src_path: str, dst_path: str, passphrase: str) -> None:
    """Stream-encrypt ``src_path`` to ``dst_path`` under ``passphrase``."""
    if not passphrase:
        raise ValueError("passphrase must be non-empty")
    salt = os.urandom(_SALT_LEN)
    nonce = os.urandom(_NONCE_LEN)
    key = _derive_key(passphrase, salt)
    cipher = Cipher(algorithms.AES(key), modes.GCM(nonce))
    enc = cipher.encryptor()
    with open(src_path, "rb") as src, open(dst_path, "wb") as dst:
        dst.write(MAGIC)
        dst.write(salt)
        dst.write(nonce)
        while True:
            block = src.read(_BLOCK)
            if not block:
                break
            dst.write(enc.update(block))
        dst.write(enc.finalize())
        dst.write(enc.tag)


def is_encrypted(path: str) -> bool:
    """True iff ``path`` begins with the at-rest magic. Cheap header
    check; doesn't validate the auth tag."""
    try:
        with open(path, "rb") as f:
            head = f.read(len(MAGIC))
    except OSError:
        return False
    return head == MAGIC


def file_is_well_formed(path: str) -> bool:
    """Structural check that ``path`` is a TSPENC01 (passphrase/at-rest)
    envelope: correct magic and room for salt + nonce + tag. Like the public-
    key check, this is a shape test, not cryptographic proof of ciphertext."""
    try:
        if os.path.getsize(path) < len(MAGIC) + _SALT_LEN + _NONCE_LEN + _TAG_LEN:
            return False
        with open(path, "rb") as f:
            return f.read(len(MAGIC)) == MAGIC
    except OSError:
        return False


def head_is_encrypted(blob: bytes) -> bool:
    """True iff an in-memory prefix looks like ciphertext we can't read —
    used to detect whether an *incoming* archive was already client-side
    encrypted before upload. Recognises both the passphrase envelope
    (``TSPENC01``, legacy ``bundle_crypto``) and the per-site public-key
    envelope (``TSPEPK01``, ``app/pubkey``). Anything else is treated as
    plaintext and rejected by the E2EE gate."""
    from . import pubkey
    return blob[:len(MAGIC)] == MAGIC or pubkey.head_is_e2ee(blob)


def decrypt_file(src_path: str, dst_path: str, passphrase: str) -> None:
    """Stream-decrypt ``src_path`` to ``dst_path`` under ``passphrase``.

    Raises ``RestDecryptError`` on any failure (wrong passphrase, magic
    mismatch, truncation, tampering)."""
    if not passphrase:
        raise RestDecryptError("passphrase required")
    try:
        with open(src_path, "rb") as src:
            magic = src.read(len(MAGIC))
            if magic != MAGIC:
                raise RestDecryptError("not a tsp-encrypted blob")
            salt = src.read(_SALT_LEN)
            nonce = src.read(_NONCE_LEN)
            if len(salt) != _SALT_LEN or len(nonce) != _NONCE_LEN:
                raise RestDecryptError("encrypted header truncated")

            src.seek(0, os.SEEK_END)
            end = src.tell()
            header_len = len(MAGIC) + _SALT_LEN + _NONCE_LEN
            tag_start = end - _TAG_LEN
            body_len = tag_start - header_len
            if body_len < 0:
                raise RestDecryptError("encrypted blob too short")
            src.seek(tag_start)
            tag = src.read(_TAG_LEN)

            key = _derive_key(passphrase, salt)
            cipher = Cipher(algorithms.AES(key), modes.GCM(nonce, tag))
            dec = cipher.decryptor()

            src.seek(header_len)
            remaining = body_len
            with open(dst_path, "wb") as dst:
                while remaining > 0:
                    block = src.read(min(_BLOCK, remaining))
                    if not block:
                        break
                    dst.write(dec.update(block))
                    remaining -= len(block)
                dst.write(dec.finalize())
    except InvalidTag as exc:
        raise RestDecryptError(
            "decryption failed — wrong passphrase or corrupted blob") from exc
    except OSError as exc:
        raise RestDecryptError(f"could not read encrypted blob: {exc}") from exc


def resolve_rest_passphrase(app) -> str:
    """The passphrase used for at-rest encryption.

    Prefers ``TSPB_REST_PASSPHRASE`` from the environment (so an operator
    can supply a memorable secret and reproduce it on a rebuilt host).
    Falls back to a random 32-byte passphrase generated once and stored
    in ``<DATA_DIR>/rest.key`` — automatic, but tied to that volume:
    losing the file means the encrypted-at-rest archives are gone.
    """
    env = os.environ.get("TSPB_REST_PASSPHRASE")
    if env:
        return env
    path = os.path.join(app.config["DATA_DIR"], "rest.key")
    if os.path.exists(path):
        with open(path, "r") as f:
            return f.read().strip()
    import secrets
    phrase = secrets.token_urlsafe(32)
    with open(path, "w") as f:
        f.write(phrase)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return phrase
