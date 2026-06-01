# SPDX-License-Identifier: AGPL-3.0-or-later
"""Data model for TS Pro Backup.

Four tables:

  * ``AdminUser``  — operators who sign into the web console.
  * ``Setting``    — a singleton row of server-wide config (Turnstile,
                     at-rest encryption, default retention policy).
  * ``Site``       — one connected TS Pro instance. Authenticates to the
                     API with a bearer key (stored only as a SHA-256
                     hash). Carries its own retention overrides.
  * ``Backup``     — one stored archive uploaded by a Site. Knows its
                     scope (``full`` whole-site vs ``frontend`` only),
                     original size / checksum, and whether the bytes on
                     disk are wrapped in the at-rest cipher.
"""
import hashlib
import secrets
from datetime import datetime

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()

# Backup scopes. ``full`` is a whole-site export (DB + uploads + keys);
# ``frontend`` is the public web frontend only. Kept as plain strings so
# TS Pro can declare new scopes without a schema change here.
SCOPE_FULL = "full"
SCOPE_FRONTEND = "frontend"
SCOPES = (SCOPE_FULL, SCOPE_FRONTEND)
SCOPE_LABELS = {SCOPE_FULL: "Whole site", SCOPE_FRONTEND: "Frontend only"}

API_KEY_PREFIX = "tspb_"


class AdminUser(UserMixin, db.Model):
    __tablename__ = "admin_user"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    # 'admin' — full access incl. server settings + user management.
    # 'user'  — normal: manage sites/backups + own password, nothing else.
    role = db.Column(db.String(16), nullable=False, default="admin")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login_at = db.Column(db.DateTime)

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)

    def is_admin(self):
        return self.role == "admin"

    @property
    def role_label(self):
        return "Admin" if self.is_admin() else "User"


class Setting(db.Model):
    """Server-wide singleton (always row id=1)."""
    __tablename__ = "setting"
    id = db.Column(db.Integer, primary_key=True)

    # Cloudflare Turnstile (gates the console login form).
    turnstile_enabled = db.Column(db.Boolean, nullable=False, default=False)
    turnstile_site_key = db.Column(db.String(255))
    turnstile_secret_key_enc = db.Column(db.LargeBinary)

    # End-to-end encryption enforcement. When on, the API rejects any
    # upload that isn't already encrypted by the client (TS Pro) before
    # it left — guaranteeing the server only ever stores ciphertext it
    # has no key for (zero-knowledge). On by default: secure by default.
    require_e2ee = db.Column(db.Boolean, nullable=False, default=True)

    # Server-side encryption at rest with AES-256-GCM (see app/restenc).
    # NOTE: this uses a key the SERVER holds, so it protects a stolen
    # disk but is NOT end-to-end. Independent of require_e2ee. Off by
    # default — with E2EE on, the bytes are already opaque to us.
    encrypt_at_rest = db.Column(db.Boolean, nullable=False, default=False)

    # Default Grandfather-Father-Son retention, applied per (site, scope)
    # unless the site overrides it. "Keep the most recent N distinct
    # days / weeks / months / years." 0 disables that tier.
    keep_daily = db.Column(db.Integer, nullable=False, default=7)
    keep_weekly = db.Column(db.Integer, nullable=False, default=4)
    keep_monthly = db.Column(db.Integer, nullable=False, default=12)
    keep_yearly = db.Column(db.Integer, nullable=False, default=3)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def get(cls):
        row = cls.query.get(1)
        if row is None:
            row = cls(id=1)
            db.session.add(row)
            db.session.commit()
        return row


class Site(db.Model):
    """A connected TS Pro instance."""
    __tablename__ = "site"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=True)

    # API key: we keep only the SHA-256 hash for verification plus a
    # short visible prefix so the operator can recognise it in the UI.
    # The full key is shown exactly once, at creation / rotation.
    api_key_hash = db.Column(db.String(64), unique=True, index=True)
    api_key_prefix = db.Column(db.String(16))

    # End-to-end encryption recipient. We store ONLY the site's public
    # key (a ``tsppk_…`` string, not a secret) — the client encrypts each
    # backup to it. The matching private key is shown to the operator
    # exactly once at creation / rotation and is never persisted here, so
    # the server can never decrypt what it stores. See ``app/pubkey.py``.
    e2ee_public_key = db.Column(db.String(80))
    # False from the moment a keypair is issued until the operator confirms
    # they've stored the (shown-once) private key. Drives a persistent
    # reminder banner — we can't know whether they actually saved it, so we
    # keep nagging until they say so. Reset to False on every rotation.
    e2ee_key_ack = db.Column(db.Boolean, nullable=False, default=False)

    # Per-site retention overrides. NULL on a tier means "inherit the
    # server default for that tier".
    keep_daily = db.Column(db.Integer)
    keep_weekly = db.Column(db.Integer)
    keep_monthly = db.Column(db.Integer)
    keep_yearly = db.Column(db.Integer)

    # Per-site overrides: NULL inherits the server default; True/False
    # force on/off for this site.
    require_e2ee = db.Column(db.Boolean)
    encrypt_at_rest = db.Column(db.Boolean)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen_at = db.Column(db.DateTime)
    last_seen_ip = db.Column(db.String(45))

    backups = db.relationship(
        "Backup", backref="site", cascade="all, delete-orphan",
        order_by="Backup.created_at.desc()",
    )

    # ── API key helpers ────────────────────────────────────────────
    @staticmethod
    def _hash_key(raw: str) -> str:
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def issue_api_key(self) -> str:
        """Generate a fresh key, store its hash + prefix, return the
        plaintext (caller must show it once and never persist it)."""
        raw = API_KEY_PREFIX + secrets.token_urlsafe(32)
        self.api_key_hash = self._hash_key(raw)
        self.api_key_prefix = raw[:12]
        return raw

    @classmethod
    def authenticate(cls, raw_key: str):
        if not raw_key:
            return None
        return cls.query.filter_by(
            api_key_hash=cls._hash_key(raw_key.strip()), enabled=True
        ).first()

    # ── E2EE keypair helpers ────────────────────────────────────────
    def issue_keypair(self) -> str:
        """Generate a fresh X25519 keypair, store the public half on the
        row, return the private key (a ``tspsk_…`` string) for the caller
        to show once and never persist. Rotating invalidates every backup
        previously encrypted to the old public key — they can still be
        decrypted with the *old* private key the operator kept."""
        from . import pubkey
        public, private = pubkey.generate_keypair()
        self.e2ee_public_key = public
        self.e2ee_key_ack = False  # operator hasn't confirmed saving this one yet
        return private

    @property
    def e2ee_fingerprint(self):
        from . import pubkey
        if not self.e2ee_public_key:
            return None
        return pubkey.fingerprint(self.e2ee_public_key)

    # ── effective retention (override → default) ───────────────────
    def retention(self, settings):
        def pick(site_val, default_val):
            return default_val if site_val is None else site_val
        return {
            "daily": pick(self.keep_daily, settings.keep_daily),
            "weekly": pick(self.keep_weekly, settings.keep_weekly),
            "monthly": pick(self.keep_monthly, settings.keep_monthly),
            "yearly": pick(self.keep_yearly, settings.keep_yearly),
        }

    def effective_encrypt_at_rest(self, settings):
        if self.encrypt_at_rest is None:
            return bool(settings.encrypt_at_rest)
        return bool(self.encrypt_at_rest)

    def effective_require_e2ee(self, settings):
        if self.require_e2ee is None:
            return bool(settings.require_e2ee)
        return bool(self.require_e2ee)

    @property
    def total_bytes(self):
        return sum(b.size_bytes or 0 for b in self.backups)


class Backup(db.Model):
    """One stored archive."""
    __tablename__ = "backup"
    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, db.ForeignKey("site.id", ondelete="CASCADE"),
                        nullable=False, index=True)

    # ``full`` | ``frontend`` (see SCOPES). Retention runs independently
    # per scope so frontend snapshots never evict whole-site ones.
    scope = db.Column(db.String(32), nullable=False, default=SCOPE_FULL, index=True)

    original_name = db.Column(db.String(255), nullable=False)
    # Opaque on-disk filename (uuid) under the site's storage dir.
    stored_name = db.Column(db.String(255), nullable=False)

    # ``size_bytes`` is the size of the archive TS Pro sent (the logical
    # backup size, before any at-rest wrapping). ``stored_bytes`` is what
    # actually sits on disk (larger if we encrypted it at rest).
    size_bytes = db.Column(db.BigInteger, nullable=False, default=0)
    stored_bytes = db.Column(db.BigInteger, nullable=False, default=0)
    sha256 = db.Column(db.String(64))  # checksum of the original bytes

    # True if WE wrapped it in the at-rest cipher (must be unwrapped on
    # download). Independent of ``client_encrypted``.
    encrypted_at_rest = db.Column(db.Boolean, nullable=False, default=False)
    # True if the incoming archive was already encrypted by TS Pro
    # (client-side). Informational — surfaced in the UI so operators know
    # the contents are opaque even after at-rest decryption.
    client_encrypted = db.Column(db.Boolean, nullable=False, default=False)

    note = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    @property
    def scope_label(self):
        return SCOPE_LABELS.get(self.scope, self.scope)
