#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Drop privileges before exec'ing the server.

The container image starts as root only so it can make the (often
root-owned, bind-mounted) data dir writable, then it permanently drops to
the unprivileged ``app`` user and exec's the real command — so gunicorn and
all request-handling code run as non-root, shrinking the blast radius of any
RCE/container-escape. Written in Python (already in the image) to avoid
adding gosu/setpriv just for this.
"""
import os
import pwd
import sys

APP_USER = "app"


def _main():
    args = sys.argv[1:]
    if not args:
        sys.stderr.write("docker-entrypoint: no command given\n")
        raise SystemExit(2)

    if os.getuid() == 0:
        pw = pwd.getpwnam(APP_USER)
        data = os.environ.get("TSPB_DATA_DIR", "/data")
        os.makedirs(data, exist_ok=True)
        # Only walk + chown the tree when ownership is actually wrong (first
        # boot / fresh bind mount); on normal restarts this is a single stat.
        try:
            if os.stat(data).st_uid != pw.pw_uid:
                for dirpath, dirnames, filenames in os.walk(data):
                    os.chown(dirpath, pw.pw_uid, pw.pw_gid)
                    for name in filenames:
                        try:
                            os.chown(os.path.join(dirpath, name), pw.pw_uid, pw.pw_gid)
                        except OSError:
                            pass
        except OSError as exc:
            sys.stderr.write(f"docker-entrypoint: could not chown {data}: {exc}\n")
        # Drop privileges: supplementary groups, then gid, then uid (last).
        os.initgroups(APP_USER, pw.pw_gid)
        os.setgid(pw.pw_gid)
        os.setuid(pw.pw_uid)
        os.environ.setdefault("HOME", pw.pw_dir or "/home/app")

    os.execvp(args[0], args)


if __name__ == "__main__":
    _main()
