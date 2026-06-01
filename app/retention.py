# SPDX-License-Identifier: AGPL-3.0-or-later
"""Grandfather-Father-Son retention.

The operator configures, per (site, scope), how many recent **distinct
days, weeks, months, and years** of backups to keep. A backup survives a
prune if it is the *newest* backup in any kept time bucket:

  * daily   — the newest backup of each of the last ``keep_daily`` days
  * weekly  — the newest backup of each of the last ``keep_weekly`` ISO weeks
  * monthly — the newest backup of each of the last ``keep_monthly`` months
  * yearly  — the newest backup of each of the last ``keep_yearly`` years

A single backup can satisfy several buckets at once (e.g. the last
backup of the month is also a daily and a weekly). Everything not picked
by any tier is deleted (row + blob). Setting a tier to 0 disables it.

Retention is evaluated independently per scope so a burst of
frontend-only snapshots can never push whole-site backups off the end.
"""
from flask import current_app

from .models import Backup, Setting, db


def _bucket_keys(dt):
    """The (day, week, month, year) bucket identifiers for a datetime."""
    iso = dt.isocalendar()  # (year, week, weekday)
    return {
        "daily": (dt.year, dt.month, dt.day),
        "weekly": (iso[0], iso[1]),
        "monthly": (dt.year, dt.month),
        "yearly": (dt.year,),
    }


def survivors(backups, policy):
    """Given backups (any order) and a policy dict of tier→count, return
    the set of backup ids to KEEP. Pure / side-effect free so it can be
    unit-reasoned and previewed in the UI."""
    ordered = sorted(backups, key=lambda b: (b.created_at, b.id), reverse=True)
    keep = set()
    for tier in ("daily", "weekly", "monthly", "yearly"):
        count = policy.get(tier, 0) or 0
        if count <= 0:
            continue
        seen = []  # ordered, newest-first, distinct bucket keys
        seen_set = set()
        for b in ordered:
            key = _bucket_keys(b.created_at)[tier]
            if key in seen_set:
                continue  # an earlier (newer) backup already claimed this bucket
            if len(seen) >= count:
                break  # this bucket is older than the window we keep
            seen.append(key)
            seen_set.add(key)
            keep.add(b.id)
    return keep


def prune_site_scope(site, scope):
    """Apply retention to one (site, scope) and delete losers. Returns the
    number of backups deleted."""
    app = current_app._get_current_object()
    settings = Setting.get()
    policy = site.retention(settings)

    backups = Backup.query.filter_by(site_id=site.id, scope=scope).all()
    if not backups:
        return 0

    keep = survivors(backups, policy)
    # If every tier is disabled, keep nothing pruned — never wipe a site
    # to zero by accident; treat all-zero as "keep everything".
    if not any((policy.get(t) or 0) > 0 for t in ("daily", "weekly", "monthly", "yearly")):
        return 0

    from .storage import delete_blob
    deleted = 0
    for b in backups:
        if b.id not in keep:
            delete_blob(app, b)
            db.session.delete(b)
            deleted += 1
    if deleted:
        db.session.commit()
        app.logger.info("retention: pruned %d backup(s) for site=%s scope=%s",
                        deleted, site.id, scope)
    return deleted
