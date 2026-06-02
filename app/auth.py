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
from werkzeug.security import check_password_hash, generate_password_hash

from . import loginguard
from .crypto import decrypt
from .models import AdminUser, Setting, db

bp = Blueprint("auth", __name__)

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

# A throwaway hash, computed once. When the submitted username doesn't
# exist we still run a password verification against this so a missing
# account takes the same time as a wrong password — closing the timing
# side channel that would otherwise let an attacker enumerate usernames.
_DUMMY_HASH = generate_password_hash("tspb-nonexistent-account-timing-equalizer")


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
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        ip = request.remote_addr

        # Turnstile FIRST: a request that fails the challenge never reaches the
        # lockout logic, so it can neither probe lock state nor (crucially)
        # accrue failures against a username. That makes the per-username
        # lockout-as-DoS lever expensive — an attacker must solve a challenge
        # for every attempt that could lock a known operator out.
        if settings.turnstile_enabled and settings.turnstile_site_key:
            token = request.form.get("cf-turnstile-response", "")
            ok, err = _verify_turnstile(settings, token, ip)
            if not ok:
                flash(err, "danger")
                return render_template("login.html")

        # Lockout check: a locked client is refused before the password is even
        # checked. Generic message: it fires on any submitted username, so it
        # leaks nothing about which accounts exist.
        locked, retry_after = loginguard.check_locked(username, ip)
        if locked:
            mins = max(1, round(retry_after / 60))
            current_app.logger.warning(
                "login locked out username=%r ip=%s", username, ip)
            flash(f"Too many failed sign-in attempts. Please wait about "
                  f"{mins} minute{'s' if mins != 1 else ''} and try again.",
                  "danger")
            return render_template("login.html"), 429

        user = AdminUser.query.filter_by(username=username).first()
        # Always run a hash verification — against the real hash if the user
        # exists, otherwise a dummy — so response time can't distinguish a
        # missing username from a wrong password.
        if user is not None:
            credentials_ok = user.check_password(password)
        else:
            check_password_hash(_DUMMY_HASH, password)
            credentials_ok = False

        if user is not None and credentials_ok:
            loginguard.clear(username, ip)
            login_user(user, remember=bool(request.form.get("remember")))
            user.last_login_at = datetime.utcnow()
            db.session.commit()
            nxt = request.args.get("next")
            return redirect(nxt if _is_safe_next(nxt) else url_for("main.dashboard"))

        loginguard.record_failure(username, ip)
        current_app.logger.info(
            "failed console login username=%r ip=%s", username, ip)
        flash("Invalid username or password", "danger")

    return render_template("login.html")


@bp.route("/force-password-change", methods=["GET", "POST"])
@login_required
def force_password_change():
    """First-login wizard shown while ``must_change_password`` is set (the
    account still has the shipped default password). The current password was
    just used to sign in, so we only ask for the new one. The before_request
    gate (see __init__._register_password_gate) funnels every other route here
    until it's done."""
    if not current_user.must_change_password:
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        new = request.form.get("new_password") or ""
        confirm = request.form.get("confirm_password") or ""
        if len(new) < 8:
            flash("Password must be at least 8 characters", "danger")
        elif new == "admin":
            flash("Please choose a password other than the default", "danger")
        elif new != confirm:
            flash("Passwords do not match", "danger")
        else:
            current_user.set_password(new)
            current_user.must_change_password = False
            # Invalidate any other session / remember cookie for this account.
            current_user.session_epoch = (current_user.session_epoch or 0) + 1
            db.session.commit()
            # Re-issue THIS session under the new epoch so the operator stays
            # signed in (otherwise the loader would reject the now-stale token).
            login_user(current_user)
            flash("Password updated — you're all set.", "success")
            return redirect(url_for("main.dashboard"))
    return render_template("force_password_change.html")


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    # POST-only (CSRF-protected): a state-changing GET would let a third-party
    # page sign the operator out via <img src=".../logout">.
    logout_user()
    return redirect(url_for("auth.login"))
