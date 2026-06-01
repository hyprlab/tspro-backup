# SPDX-License-Identifier: AGPL-3.0-or-later
"""Console authentication + Cloudflare Turnstile.

A single shared admin login (Flask-Login). When Turnstile is enabled in
Settings, the login form renders the widget and the POST handler verifies
the token server-side against Cloudflare before checking credentials —
failing closed on any verification error, mirroring TS Pro's behaviour.
"""
from datetime import datetime
from urllib.parse import urljoin, urlparse

from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, url_for)
from flask_login import current_user, login_required, login_user, logout_user

from .crypto import decrypt
from .models import AdminUser, Setting, db

bp = Blueprint("auth", __name__)

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


def _is_safe_next(target):
    if not target:
        return False
    ref = urlparse(request.host_url)
    test = urlparse(urljoin(request.host_url, target))
    return test.scheme in ("http", "https") and ref.netloc == test.netloc


def _verify_turnstile(settings, token, remote_ip):
    """Returns (ok, error_message). Fails closed on any failure."""
    import requests
    secret = decrypt(settings.turnstile_secret_key_enc) if settings.turnstile_secret_key_enc else ""
    if not secret:
        return False, "Turnstile is enabled but no secret key is configured"
    if not token:
        return False, "Please complete the security check"
    try:
        resp = requests.post(
            TURNSTILE_VERIFY_URL,
            data={"secret": secret, "response": token, "remoteip": remote_ip or ""},
            timeout=5,
        )
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        current_app.logger.warning("Turnstile verify failed: %s", exc)
        return False, "Security check failed — please try again"
    if data.get("success"):
        return True, None
    return False, "Security check failed — please try again"


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    settings = Setting.get()
    if request.method == "POST":
        if settings.turnstile_enabled and settings.turnstile_site_key:
            token = request.form.get("cf-turnstile-response", "")
            ok, err = _verify_turnstile(settings, token, request.remote_addr)
            if not ok:
                flash(err, "danger")
                return render_template("login.html")

        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = AdminUser.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user, remember=bool(request.form.get("remember")))
            user.last_login_at = datetime.utcnow()
            db.session.commit()
            nxt = request.args.get("next")
            return redirect(nxt if _is_safe_next(nxt) else url_for("main.dashboard"))
        flash("Invalid username or password", "danger")

    return render_template("login.html")


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
