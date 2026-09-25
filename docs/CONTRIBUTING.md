# Contributing

The conventions anyone editing this repository follows, human or AI. Bug
reports, ideas and pull requests are all welcome, and a clear bug report is
often as useful as a patch.

## Setting up

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
git config core.hooksPath tools/git-hooks     # once per clone or worktree
.venv/bin/python -m pytest
TSPB_SECRET_KEY=dev-secret TSPB_DEBUG=1 .venv/bin/python run.py   # http://localhost:8000
```

The hooks enforce the commit rules below and run the documentation check.
Without `core.hooksPath` they silently do nothing, so set it in every clone
and every worktree.

To try a change the way it will run in production, rebuild the container:
`tools/redeploy.sh`.

## Commits

**The history is the maintainer's.** Commits carry no AI tool attribution: no
`Co-Authored-By:` line for Claude or any other assistant, no "Generated with"
footer, no session line, in a commit, a tag message, a pull request body or a
release body. The [AI notice](../README.md#ai-notice) declares how the project
is built, once, for the whole repository. One stray trailer puts the tool on
GitHub's Contributors panel, and removing it again means rewriting history
(it was done once, on 2026-09-25).

A `Co-Authored-By:` trailer is still how a **person** is credited, with the
GitHub noreply address that resolves to their profile (see
[Credit](#credit)).

Subjects follow [Conventional Commits](https://www.conventionalcommits.org):
`type(area): summary`, lower case after the colon, imperative, no full stop,
72 characters at most and ideally nearer 50.

- Types: `feat`, `fix`, `perf`, `refactor`, `docs`, `build`, `ci`, `test`,
  `style`, `chore`, `revert`. A `!` after the type (`feat(api)!:`) marks a
  breaking change. The type is not decoration: `tools/next-version.sh` reads
  it to decide the next version ([RELEASING.md](RELEASING.md)).
- The area is where the change lives: `api`, `console`, `auth`, `storage`,
  `retention`, `crypto`, `restore`, `db`, `docker`, `docs`, `release`. Leave
  it out only when there is no single place.
- An issue number goes at the end: `fix(api): refuse an empty chunk (#12)`.
- Releases: `chore(release): 1.4.0`, `chore(release): 1.5.0-beta.1`.

The body is optional and short: why the change exists, never what the diff
already says. Past 100 words the detail belongs in `docs/` or `CHANGELOG.md`,
or the commit wants splitting. **Each body paragraph is one line, not
wrapped:** GitHub keeps every line break in a body, so text wrapped at 72
breaks a second time on a phone. Write it with `git commit -F -` and a heredoc.

`tools/git-hooks/commit-msg` refuses the attribution lines, em dashes, a
subject without a type, and an overlong subject or body. `pre-push` refuses to
publish any commit or tag carrying attribution.

## CLAUDE.md and .claude/

Both are local only: listed in `.git/info/exclude`, not `.gitignore`, so the
repository never names the tool. Never `git add -f` them. A new worktree does
not get them: symlink `CLAUDE.md` into it before working there.

## Prose style

Documentation, the changelog, release notes, UI text and issue replies:

- Factual, plain language. Say what the app does, not what it enables you to
  do. No marketing, no superlatives, no "finally", no emoji.
- **No em dashes** anywhere: not in commits, the README, `docs/`, the
  changelog, release titles or notes, or GitHub comments. A colon, a comma or
  a full stop replaces them. `tools/check-docs.py` and the commit hook refuse
  them.
- American spelling in anything the app shows: color, behavior, canceled.
- Changelog lines describe the change from the user's side. How it was built
  belongs in the commit.
- Comments in code explain *why*, not *what*.

## Documentation

The README is the front door and has a 200-line ceiling. Before writing a word
of documentation, decide where it goes: the table in
[docs/README.md](README.md) says. After touching any `.md`, run:

```sh
python3 tools/check-docs.py
```

It checks every relative link and anchor, that every `docs/*.md` is indexed,
that `docs/` holds Markdown only, the README's length, the changelog's shape
and version, and that no Markdown file contains an em dash.

Every release, patches included, gets a `CHANGELOG.md` section.

## Code

- Match what is there: the app factory, the three blueprints, JSON errors as
  `{"ok": false, "error": "..."}` on the API.
- A new model column needs a matching entry in `_migrate_sqlite()` in
  `app/__init__.py`, or upgraded installs break. A migration an older version
  can't read back is a MAJOR release.
- `app/pubkey.py` stays byte-identical to TS Pro's copy.
- Anything a user typed is rendered with Jinja's escaping, never `|safe`.
- User-facing failures say what happened and what to do, in a sentence.
- Tests before committing (`pytest`), and rebuild and run the app
  (`tools/redeploy.sh`) before saying something works.

## Credit

Outside pull requests land as commits on `main` made by the maintainer,
crediting the author with a trailer that uses their GitHub noreply address:

```
Co-Authored-By: Jane Doe <12345678+janedoe@users.noreply.github.com>
```

Get the id with `gh api users/<login> --jq .id`. An address taken from their
own commit may not be linked to their account, and then they never appear as a
contributor; that can't be fixed after a tagged release without rewriting
history.

Add them to `CONTRIBUTORS` (their name and `@login`) and describe the work in
[CREDITS.md](CREDITS.md). Close the pull request with a comment saying what
was taken, what changed and what was left out.

In release notes an `@` is for people whose code, art or translation is in the
release. Reporters and requesters are named without the `@`: an @ notifies
someone and reads as authorship. `tools/release-notes.sh` strips the @ from any
handle not in `CONTRIBUTORS`.

## Issue replies

Every reply to an issue or pull request written by an agent begins with
`*Agentic reply:*` in italics, then a blank line, then the reply.

- A reply saying something is done is one or two sentences: what changed from
  the user's side, and which version carries it. How it was built is in the
  commit and the changelog.
- No thanks, no pleasantries, no em dashes. Plain, brief, human.
- Anything the user has to do (send a log, try something, check a setting) is
  a numbered list, one request per item.
- Fixed in a beta: name the beta version and say it reaches stable with the
  next stable release. The issue closes when that stable ships.
- Fixed in a stable: name the version and how to update. Reply once the image
  is pushed, not before.

```
*Agentic reply:*

Fixed in 1.4.0: chunked uploads over 4 GiB now finalize.

Update with `docker compose pull && docker compose up -d`.
```

Only a reply that asks for something or explains a decline runs longer.
