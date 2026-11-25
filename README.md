# TDS change monitor

Sends alerts to **Telegram, a shared Google Chat space, or both** when the
**public** Tools in Data Science dashboard changes: a deadline moves, a graded
assignment goes live, the schedule is edited.

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

python monitor.py --test-notification  # test delivery without changing the baseline
python monitor.py --dry-run   # preview the alert without saving anything
python monitor.py             # first run saves a baseline, then notifies on changes
python monitor.py --status    # show what is being watched
```

For **Google Chat only**, set `GOOGLE_CHAT_WEBHOOK_URL` instead of the two
Telegram variables (see setup below). To notify both, configure all three.
Variables can also be stored in a local `.env`; see `.env.example` for the
available destinations. Leave unused destinations blank, and don't overwrite an
existing `.env` containing your credentials.

The first real monitoring run sends one "Baseline saved" message to every
configured destination, then saves the baseline. After that it stays quiet until
something changes. `--test-notification` sends a test even when a baseline already
exists, without fetching course data or writing `state.json`.

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

## Google Chat setup (shared notifications)

1. Open [Google Chat](https://chat.google.com/) in a browser. Create or choose a
   **space** and invite the friends who should see the alerts. Everyone in that
   space can see the webhook's messages; individual notification settings still
   determine whether they receive a push notification.
2. Click the space title → **Apps & integrations** → **Add webhooks**.
3. Name the webhook, for example `TDS deadlines`, and save it. Use its **More**
   menu → **Copy link** to copy the incoming webhook URL.
4. Add the URL to your local `.env`, or export it:

   ```bash
   export GOOGLE_CHAT_WEBHOOK_URL="https://chat.googleapis.com/v1/spaces/SPACE_ID/messages?key=KEY&token=TOKEN"
   ```

   Use the full URL copied from Chat, not the example placeholders. No Telegram
   credentials are needed for Google Chat only. Keep your existing Telegram
   configuration if you want personal alerts as well as shared alerts.
5. Run `python monitor.py --test-notification` and check the space for the test
   message. This does not reset your saved baseline.

**Account requirement:** Google's [webhook documentation](https://developers.google.com/workspace/chat/quickstart/webhooks)
lists a Business or Enterprise Google Workspace account as a prerequisite, and
the organization must permit incoming webhooks. If **Add webhooks** is missing
or disabled, check with your Workspace admin. A personal Gmail account doesn't
meet the documented prerequisite. Your organization may also restrict inviting
friends from outside the organization.

**Keep the webhook URL secret.** It contains credentials that let anyone with
the URL post to your space. Store it in `.env` (git-ignored) or a GitHub Actions
secret, never in a public commit. Friends only need to join the space, not know
the webhook URL. This is a one-way notification integration, not a bot that
responds to messages.

### Google Chat alert layout

Chat alerts use native **cards**, rather than a wall of text:

- A compact header with the term and check time in IST.
- An at-a-glance update count, followed by separate deadline, schedule, new
  assessment, and instruction-edit sections.
- New dates highlighted in blue, with previous dates underneath for comparison.
- **Open assessment**, **View schedule**, and **View commits** buttons linking
  directly to the public sources.
- Collapsible commit context to keep the important updates easy to scan.
- A plain-text fallback for mobile notification previews. Very large change sets
  are bounded, with source links for details; oversized cards fall back to text.

Telegram keeps its existing HTML-formatted alerts. The test command sends a
matching setup card to Google Chat, clearly labeled as a test rather than a
course change.

## Deploy on GitHub Actions

1. Push this folder to a GitHub repo. **Make it public** — Actions minutes are
   unlimited there, and this workflow runs every hour.
2. Repo → *Settings → Secrets and variables → Actions* → add the secrets for
   your chosen destinations:
   - Telegram: `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
   - Google Chat: `GOOGLE_CHAT_WEBHOOK_URL`.
   - Both: all three secrets. Leave unused destinations unconfigured.
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
change    → format alerts → send to configured destinations → save/commit new state
```

The baseline advances only after **all configured destinations** accept the
alert. If one delivery fails, the run reports an error and the next monitoring
run retries the change. A destination that already succeeded may receive a
duplicate on that retry. Dry runs never send messages or change the baseline.

Two details that keep the signal high:

- **Field-level diffs.** The README table is parsed into rows, so an alert says
  `GA4 submission: Sun 08 Nov → Sun 15 Nov`, not "the page changed".
- **Commits are context, not a trigger.** Blog posts and image commits in the
  course repo do not page you; they are only attached to a real schedule or
  assessment change.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | optional; set together with `TELEGRAM_CHAT_ID` for Telegram |
| `TELEGRAM_CHAT_ID` | — | optional; set together with `TELEGRAM_BOT_TOKEN` for Telegram |
| `GOOGLE_CHAT_WEBHOOK_URL` | — | optional; incoming webhook URL for a shared Google Chat space |
| `TDS_TERM` | auto from `terms.yml` | pin a term, e.g. `2026-09` |
| `TDS_REPO` | `sanand0/tools-in-data-science-public` | source repo |
| `STATE_PATH` | `state.json` | baseline file |
| `DRY_RUN` | off | set `1` to log messages instead of sending (also works as a repo Actions *variable*) |

At least one destination is required when sending. Partially configured Telegram
credentials are treated as an error, even if Google Chat is also configured.
`--dry-run`, `--seed`, and `--status` do not require notification credentials.

CLI: `--dry-run` preview, `--seed` reset baseline silently, `--status` show what is
being watched, `--test-notification` test delivery without polling or changing
state. Use `--test-notification --dry-run` to preview the test without sending it.

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
  notify.py                Telegram / Google Chat formatting and sending
  cards.py                 structured Google Chat alert and test card layouts
tests/                     parser, configuration, notification, run, and CLI tests
.env.example               optional notification settings (no credentials)
.github/workflows/monitor.yml
```

## Tests

```bash
python -m unittest discover -s tests -v
```
