# SPDX-License-Identifier: AGPL-3.0-or-later
"""TS Pro Backup — application factory.

A standalone Flask service that receives off-site backups from one or
more Trusted Servants Pro instances over an authenticated HTTP API,
stores them (optionally AES-256 encrypted at rest), enforces a
grandfather-father-son retention policy, and offers a web console — built
to match the TS Pro look — for operators to manage sites and browse
backups.

Like TS Pro itself there is no Alembic: ``_migrate_sqlite`` additively
patches columns onto existing tables at boot, ``db.create_all`` handles
fresh installs.
"""
import os
from datetime import datetime

from flask import Flask
from flask_login import LoginManager
from flask_wtf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

from .crypto import init_fernet
from .models import AdminUser, Setting, db
from .version import __version__

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = None
csrf = CSRFProtect()


def create_app():
    app = Flask(__name__)

    data_dir = os.environ.get("TSPB_DATA_DIR", "/data")
    os.makedirs(data_dir, exist_ok=True)
    db_path = os.path.join(data_dir, "tspro_backup.db")

    max_mb = int(os.environ.get("TSPB_MAX_UPLOAD_MB", "8192"))

    app.config.update(
        SECRET_KEY=os.environ.get("TSPB_SECRET_KEY", "dev-insecure-change-me"),
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{db_path}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        DATA_DIR=data_dir,
        DB_PATH=db_path,
        VERSION=__version__,
        MAX_CONTENT_LENGTH=max_mb * 1024 * 1024,
        # Secure cookie unless explicitly running over plain HTTP for dev.
        SESSION_COOKIE_SECURE=os.environ.get("TSPB_DEBUG", "").lower()
        not in ("1", "true", "yes"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )

    # Behind Caddy / Cloudflare: trust one proxy hop for scheme + client IP
    # so Turnstile sees the real remote address and url_for builds https.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    init_fernet(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from .auth import bp as auth_bp
    from .routes import bp as main_bp
    from .api import bp as api_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)
    # TS Pro instances authenticate with an API key, not a session cookie —
    # the API is stateless, so exempt it from form-CSRF entirely.
    csrf.exempt(api_bp)

    _register_jinja(app)

    with app.app_context():
        db.create_all()
        _migrate_sqlite(db)
        Setting.get()  # ensure singleton exists
        _seed_admin(app)

    return app


@login_manager.user_loader
def _load_user(user_id):
    return AdminUser.query.get(int(user_id))


def _seed_admin(app):
    if AdminUser.query.first() is not None:
        return
    username = os.environ.get("TSPB_ADMIN_USERNAME", "admin")
    password = os.environ.get("TSPB_ADMIN_PASSWORD", "admin")
    u = AdminUser(username=username, role="admin")
    u.set_password(password)
    db.session.add(u)
    db.session.commit()
    app.logger.info("Seeded initial admin user %r", username)


def _migrate_sqlite(db):
    """Additively patch columns missing from existing tables. Mirrors TS
    Pro's approach: every column added to a model after first release must
    get an entry here so upgraded deployments don't break."""
    from sqlalchemy import text

    def cols(table):
        rows = db.session.execute(text(f"PRAGMA table_info({table})")).fetchall()
        return {r[1] for r in rows}

    def add(table, name, ddl):
        # Commit each column on its own and swallow a concurrent "duplicate
        # column" — with multiple gunicorn workers booting at once, two can
        # race the same ALTER; the loser's error is benign.
        if name in cols(table):
            return
        try:
            db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))
            db.session.commit()
        except Exception:  # noqa: BLE001
            db.session.rollback()

    try:
        existing = {r[0] for r in db.session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()}
        if "setting" in existing:
            add("setting", "require_e2ee", "require_e2ee BOOLEAN DEFAULT 1")
            add("setting", "encrypt_at_rest", "encrypt_at_rest BOOLEAN DEFAULT 0")
            add("setting", "keep_daily", "keep_daily INTEGER DEFAULT 7")
            add("setting", "keep_weekly", "keep_weekly INTEGER DEFAULT 4")
            add("setting", "keep_monthly", "keep_monthly INTEGER DEFAULT 12")
            add("setting", "keep_yearly", "keep_yearly INTEGER DEFAULT 3")
        if "admin_user" in existing:
            add("admin_user", "role", "role VARCHAR(16) DEFAULT 'admin'")
        if "site" in existing:
            add("site", "require_e2ee", "require_e2ee BOOLEAN")
            add("site", "encrypt_at_rest", "encrypt_at_rest BOOLEAN")
            add("site", "last_seen_ip", "last_seen_ip VARCHAR(45)")
            add("site", "e2ee_public_key", "e2ee_public_key VARCHAR(80)")
            add("site", "e2ee_key_ack", "e2ee_key_ack BOOLEAN DEFAULT 0")
        if "backup" in existing:
            add("backup", "client_encrypted", "client_encrypted BOOLEAN DEFAULT 0")
            add("backup", "note", "note VARCHAR(500)")
        db.session.commit()
    except Exception as e:  # noqa: BLE001 — never let a migration crash boot
        db.session.rollback()
        import logging
        logging.getLogger(__name__).warning("migration skipped: %s", e)


def _register_jinja(app):
    from flask_login import current_user
    from .icons import ICONS

    @app.context_processor
    def inject_globals():
        # The settings modal lives in base.html on every authenticated page;
        # only an admin needs the user list, so skip the query otherwise.
        console_users = []
        if current_user.is_authenticated and current_user.is_admin():
            console_users = AdminUser.query.order_by(AdminUser.username).all()
        return {
            "app_version": __version__,
            "settings": Setting.get(),
            "console_users": console_users,
            "now": datetime.utcnow(),
            "icon": lambda name: ICONS.get(name, ""),
        }

    @app.template_filter("fmt_bytes")
    def fmt_bytes(n):
        n = float(n or 0)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if n < 1024 or unit == "TB":
                return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
            n /= 1024

    @app.template_filter("fmt_dt")
    def fmt_dt(dt):
        if not dt:
            return "—"
        return dt.strftime("%Y-%m-%d %H:%M UTC")

    @app.template_filter("ago")
    def ago(dt):
        if not dt:
            return "never"
        delta = datetime.utcnow() - dt
        s = int(delta.total_seconds())
        if s < 60:
            return "just now"
        if s < 3600:
            return f"{s // 60}m ago"
        if s < 86400:
            return f"{s // 3600}h ago"
        return f"{s // 86400}d ago"
