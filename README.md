# TDS change monitor

Pings you on Telegram when the **public** Tools in Data Science dashboard changes:
a deadline moves, a graded assignment goes live, the schedule is edited.

No login, no cookies, no scraping of your private data.

```
🔔 TDS 2026-09 · 31 Oct 2026 11:21 IST

📅 Schedule
• GA4 submission: Sun 08 Nov → Sun 15 Nov

🎉 New assessment released
• GA5 — TDS 2026 Sep GA5
  https://exam.sanand.workers.dev/tds-2026-09-ga5
```

## What it watches

| Source | Detects | Auth |
|---|---|---|
| `raw.githubusercontent.com/.../terms.yml` | which term is current (auto-rollover) | none |
| `raw.githubusercontent.com/.../{term}/README.md` | schedule table: dates, weights, rows added/removed | none |
| `exam.sanand.workers.dev/exam-tds-{term}-{id}.info.js` | assessment released, exact open/close timestamps, instructions edits | none |
| `github.com/.../commits/main.atom` | commit context attached to a real change | none |

The exam `info.js` files are the useful trick: they only exist **after** an
assessment is published, and they carry the authoritative `start`/`end`
timestamps with the timezone. So a `404 → 200` flip is a reliable
"new assignment is live" signal, and an `end` change is a real deadline move.

## What it deliberately does not watch

| Skipped | Why |
|---|---|
| Seek notifications bell | login required; would need your cookies |
| Marks / grade card | same, and it is private data |
| TDS Discourse | returns `403 not_logged_in` to anonymous clients |
| Exam question text | served per-session by a question server, not in the public file |

If you later want those, add a cookie-backed fetch — but expect to re-login
every few weeks.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export TELEGRAM_BOT_TOKEN="123456:ABC..."
export TELEGRAM_CHAT_ID="987654321"

python monitor.py --dry-run   # preview the alert without saving anything
python monitor.py             # first run saves a baseline, then notifies on changes
python monitor.py --status    # show what is being watched
```

The first real run saves a baseline and sends one "Baseline saved" message,
which also proves your credentials work. After that it stays quiet until
something changes.

## Telegram setup (2 minutes)

1. Message [@BotFather](https://t.me/BotFather), send `/newbot`, pick a name.
   Copy the token it gives you.
2. **Send any message to your new bot.** Telegram bots cannot start a
   conversation, so this step is required.
3. Find your chat id:

   ```bash
   curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates" | head -c 500
   ```

   Look for `"chat":{"id":123456789`.
4. Use the token and that id as `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`.

## Deploy on GitHub Actions

1. Push this folder to a GitHub repo. **Make it public** — Actions minutes are
   unlimited there, and this workflow runs every hour.
2. Repo → *Settings → Secrets and variables → Actions* → add
   `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
3. Repo → *Actions* tab → enable workflows → run **TDS change monitor** once
   manually to seed.
4. Done. `state.json` is committed back after every run, so each run compares
   against the previous one.

`state.json` is the memory. Delete it (or run `python monitor.py --seed`) to
start over with a fresh baseline.

## How a run works

```
fetch term + README + exam files + commits
        ↓
parse into {schedule: {...}, exams: {...}}
        ↓
diff against state.json
        ↓
no change → exit quietly, nothing written
change    → format Telegram message → send → commit new state
```

Two details that keep the signal high:

- **Field-level diffs.** The README table is parsed into rows, so an alert says
  `GA4 submission: Sun 08 Nov → Sun 15 Nov`, not "the page changed".
- **Commits are context, not a trigger.** Blog posts and image commits in the
  course repo do not page you; they are only attached to a real schedule or
  assessment change.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | required unless `--dry-run` |
| `TELEGRAM_CHAT_ID` | — | required unless `--dry-run` |
| `TDS_TERM` | auto from `terms.yml` | pin a term, e.g. `2026-09` |
| `TDS_REPO` | `sanand0/tools-in-data-science-public` | source repo |
| `STATE_PATH` | `state.json` | baseline file |
| `DRY_RUN` | off | set `1` to log messages instead of sending (also works as a repo Actions *variable*) |

CLI: `--dry-run` preview, `--seed` reset baseline silently, `--status` show what is being watched.

## Maintenance notes

- **GitHub disables scheduled workflows after 60 days of repo inactivity.**
  You will get an email when that happens; re-enable it in the Actions tab.
- Scheduled runs are best-effort and can lag 5–20 minutes. Fine for deadlines,
  not for second-by-second monitoring.
- Polling is ~15 requests per hour total. Please keep it in that range.
- When the term changes, `terms.yml` flips `current:` and the monitor
  re-baselines automatically. You get one "Baseline saved" message.

## Layout

```
monitor.py                 CLI entry point
tds_watch/
  config.py                env vars
  sources.py               public HTTP fetches + Atom parsing
  parse.py                 markdown table + info.js parsers
  run.py                   collect → diff → notify
  state.py                 atomic JSON read/write
  notify.py                Telegram formatting and sending
tests/test_parse.py        parser tests
.github/workflows/monitor.yml
```

## Tests

```bash
python -m unittest discover -s tests -v
```
