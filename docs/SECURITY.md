# Security

## Reporting a problem

Report security problems privately, by email to hyprlab@proton.me. Please
don't open a public issue.

Expect a reply within a week. A fix ships as an urgent patch release
([RELEASING.md](RELEASING.md#urgent-patches)), the reporter is credited in the
changelog unless they ask not to be, and an embargo the reporter proposes is
respected, ending when the fixed release ships.

Only the latest stable release receives security fixes.

## The security model

The server is built to be unable to read what it stores. With end-to-end
encryption on (the default), every backup arrives encrypted to a key only the
operator holds, and the server keeps no copy of that key. Someone who takes
over the server, or copies its storage, gets ciphertext. The layers are
described in [ARCHITECTURE.md](ARCHITECTURE.md#encryption).

| Threat | Defense |
| --- | --- |
| Reading stored backups | End-to-end encryption to the operator's key; uploads that aren't a well-formed envelope are refused |
| A stolen API key | Scoped to one site; can't read another site's backups; restore endpoint changes need the operator's confirmation, and an admin can pin the host |
| A stolen restore token | The portal also requires the operator's private key before it restores anything |
| Password guessing | scrypt hashes; lockout per username and per IP; optional Cloudflare Turnstile |
| A default password | `admin` / `admin` must be changed before anything else is reachable |
| Session theft | `HttpOnly`, `Secure` and `SameSite` cookies; every session ends on a password change |
| Cross-site request forgery | A CSRF token on every console form |
| Clickjacking and injection | CSP, `X-Frame-Options`, `nosniff` and HSTS headers |
| Filling the disk | Upload size caps, chunk caps, a free-space check and optional per-site quotas |
| A compromised process | The container drops to an unprivileged user, with no new privileges and minimal capabilities |

## Out of scope

- TLS is the reverse proxy's job.
- The server can't verify an end-to-end envelope's authentication tags
  without the private key; it checks the envelope's structure, and
  tampering is detected at restore.
- Losing the private key loses the backups made with it. That is the cost
  of the server being unable to read them.
