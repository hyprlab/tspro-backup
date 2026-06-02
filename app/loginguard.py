# SPDX-License-Identifier: AGPL-3.0-or-later
"""Failed-login rate limiting / lockout for the console.

The console sign-in form is the one password-guessable surface on this
server (the API is gated by a 256-bit key, not a password). Without a
limit, an attacker can brute-force the operator password — and the seed
admin is a well-known ``admin`` account. This module adds a sliding-window
lockout:

  * Every *failed* sign-in is recorded as a ``LoginAttempt`` row, keyed by
    both the submitted username and the client IP.
  * A sign-in is refused — *before* the password is even checked — when
    EITHER the username OR the IP has accrued ``LOGIN_MAX_FAILURES``
    failures within the trailing ``LOGIN_WINDOW_MINUTES`` window.
  * A successful sign-in clears that username's and that IP's failures.

State lives in the DB (not process memory) so it holds across gunicorn
workers and restarts — an in-memory counter would only see a fraction of
the attempts under the default 2-worker deployment.

Locking on *both* axes is deliberate. Per-IP stops one source spraying
many usernames; per-username stops a distributed attack on one account.
The per-username axis is also a denial-of-service lever (an attacker can
lock a known operator out for the window), so the window is kept short and
Cloudflare Turnstile remains the recommended first gate — see README /
the hardening notes.
"""
from datetime import datetime, timedelta

from flask import current_app

from .models import LoginAttempt, db

# Defaults; overridable via app.config (seeded from env in create_app).
_DEFAULT_MAX_FAILURES = 5
_DEFAULT_WINDOW_MINUTES = 15


def _max_failures():
    return int(current_app.config.get("LOGIN_MAX_FAILURES", _DEFAULT_MAX_FAILURES))


def _window():
    minutes = int(current_app.config.get("LOGIN_WINDOW_MINUTES", _DEFAULT_WINDOW_MINUTES))
    return timedelta(minutes=minutes)


def _norm(username):
    return (username or "").strip().lower()


def check_locked(username, ip):
    """Return ``(locked, retry_after_seconds)``.

    Locked when either the username or the IP has at least
    ``_max_failures()`` failures inside the trailing window. The retry
    estimate is how long until enough of the *oldest* qualifying failures
    age out of the window for the count to drop back below the threshold —
    so the lock self-clears without a background job.
    """
    threshold = _max_failures()
    if threshold <= 0:
        return False, 0
    now = datetime.utcnow()
    cutoff = now - _window()

    locked_until = None
    for column, value in ((LoginAttempt.username, _norm(username)),
                          (LoginAttempt.ip, (ip or "").strip())):
        if not value:
            continue
        times = [
            row.created_at for row in (
                LoginAttempt.query
                .filter(column == value, LoginAttempt.created_at > cutoff)
                .order_by(LoginAttempt.created_at.asc())
                .all()
            )
        ]
        if len(times) >= threshold:
            # The failure that must age out for the count to fall below the
            # threshold is the (count - threshold + 1)-th oldest == times[-threshold].
            until = times[-threshold] + _window()
            if locked_until is None or until > locked_until:
                locked_until = until

    if locked_until and locked_until > now:
        return True, int((locked_until - now).total_seconds()) + 1
    return False, 0


def record_failure(username, ip):
    """Record one failed attempt and opportunistically prune stale rows."""
    db.session.add(LoginAttempt(username=_norm(username), ip=(ip or "").strip() or None))
    db.session.commit()
    _prune()


def clear(username, ip):
    """Forget the just-authenticated username's failures after a success.

    Deliberately does NOT wipe the IP axis: on a shared egress (corporate
    NAT, a proxy's egress IP) one honest login must not reset the per-IP
    failure budget an attacker is accruing against *other* usernames from
    the same address."""
    u = _norm(username)
    if u:
        LoginAttempt.query.filter_by(username=u).delete(synchronize_session=False)
        db.session.commit()


def _prune():
    """Drop attempts older than the window — they can never affect a lock.
    Best-effort: a prune failure must never block a login response."""
    try:
        cutoff = datetime.utcnow() - _window()
        LoginAttempt.query.filter(LoginAttempt.created_at < cutoff).delete(
            synchronize_session=False)
        db.session.commit()
    except Exception:  # noqa: BLE001
        db.session.rollback()
