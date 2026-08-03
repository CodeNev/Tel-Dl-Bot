# Telegram Universal Media Downloader Bot

A production-ready, async Telegram bot that detects links from any site supported
by [yt-dlp](https://github.com/yt-dlp/yt-dlp) (YouTube, TikTok, Instagram, X/Twitter,
Facebook, Reddit, Vimeo, Twitch, SoundCloud, Dailymotion, and hundreds more), shows a
rich metadata preview, and lets the user pick a quality to download.

> ⚠️ **Legal note**: Only use this bot to download content you own, that is
> licensed for reuse, or that the source platform's terms of service permit
> downloading. You are responsible for complying with the terms of service of
> every platform you use this bot against, and with applicable copyright law.

---

## Features

- Auto-detects supported links in private chats, groups, and supergroups
- Extracts metadata (title, thumbnail, duration, uploader, upload date, resolution,
  estimated size) before downloading anything
- Dynamic inline keyboard with only the quality options that actually exist
  (2160p / 1440p / 1080p / 720p / 480p / 360p / audio-only MP3)
- Automatic audio+video merging with FFmpeg, MP4 preferred
- Live progress updates (extracting → downloading → merging → uploading → done)
- Async job queue with configurable concurrency, queue size, and cancellation
- Per-user rate limiting and message de-duplication
- TTL cache for metadata/thumbnails with automatic expiry
- Friendly error messages for private/deleted/age-restricted/geo-blocked videos
- Structured logging of downloads, errors, warnings, and timings
- Hardened against command injection, path traversal, and malformed URLs
- One-file Docker deployment, tuned for Railway's Free/Hobby plans

---

## Architecture

```
bot/
  handlers/        Telegram update handlers (messages, callbacks, commands, errors)
  downloaders/      yt-dlp wrapper: metadata extraction + format-specific downloads
  services/         Queue manager, progress reporter, session store, app context
  middlewares/      Access control: dedup, rate limiting, chat-type filtering
  database/         Async SQLite: dedup tracking, rate limits, download history
  cache/            TTL cache for metadata/thumbnails
  utils/            Logging, URL validation/sanitization, formatting helpers
  config/           Environment-variable driven settings with startup validation
main.py             Wires everything together and starts polling
```

**Flow for a downloaded video:**

1. `handle_message` detects a URL, checks dedup/rate-limit/chat-type, then calls
   `YTDLPService.extract_info` (cached by URL in `CacheManager`).
2. A `PendingSession` is created in `SessionStore` with a short token, and an
   inline keyboard is sent whose `callback_data` is `dl:<token>:<format_id>`.
3. On button press, `handle_callback` looks up the session, submits a job to
   `DownloadQueueManager` (bounded by `MAX_CONCURRENT_DOWNLOADS` /
   `MAX_QUEUE_SIZE`), and a `ProgressReporter` throttles message edits.
4. `YTDLPService.download` downloads (merging via FFmpeg if needed) in a
   thread executor, and the resulting file is streamed to Telegram, then deleted.

---

## Requirements

- Python 3.12+
- FFmpeg (installed automatically in the provided Dockerfile)
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

---

## Local installation

```bash
git clone <this-repo>
cd telegram-media-bot
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and set BOT_TOKEN (and ADMIN_IDS if you want /stats access)
python main.py
```

FFmpeg must be on your PATH locally. On macOS: `brew install ffmpeg`. On
Ubuntu/Debian: `sudo apt install ffmpeg`. On Windows, download a build from
ffmpeg.org and add it to PATH, or set `FFMPEG_PATH` to the full binary path.

---

## Railway deployment

1. Push this repository to your own GitHub repo (or use Railway's "Deploy from
   GitHub" / "Empty project + upload" flow).
2. In Railway, create a new project from that repo. Railway will detect the
   `Dockerfile` and `railway.json` and build automatically — no manual
   configuration of build/start commands is needed.
3. Open the **Variables** tab on your Railway service and paste in the block
   below (Railway's raw editor accepts `KEY=VALUE` pairs, one per line), then
   replace the placeholder values:

   ```
   BOT_TOKEN=YOUR_BOT_TOKEN
   ADMIN_IDS=YOUR_ADMIN_ID
   LOG_LEVEL=INFO
   MAX_FILE_SIZE=2000
   MAX_CONCURRENT_DOWNLOADS=3
   DOWNLOAD_TIMEOUT=600
   CACHE_DIR=/tmp/cache
   TEMP_DIR=/tmp/downloads
   ENABLE_CACHE=true
   CACHE_EXPIRE_HOURS=24
   ENABLE_AUTO_DETECTION=true
   ENABLE_PRIVATE_CHAT=true
   ENABLE_GROUPS=true
   ENABLE_SUPERGROUPS=true
   ENABLE_PROGRESS_BAR=true
   MAX_QUEUE_SIZE=50
   RATE_LIMIT_PER_USER=5
   ALLOWED_DOMAINS=*
   BLOCKED_DOMAINS=
   COOKIE_FILE=
   PROXY_URL=
   FFMPEG_PATH=ffmpeg
   YTDLP_BINARY=yt-dlp
   TELEGRAM_API_ID=
   TELEGRAM_API_HASH=
   ```

4. At minimum, set `BOT_TOKEN` to your real token from @BotFather. Set
   `ADMIN_IDS` to your numeric Telegram user ID (get it from
   [@userinfobot](https://t.me/userinfobot)) if you want access to `/stats`.
5. Deploy. Railway will build the Docker image (which installs FFmpeg) and
   start the bot with `python main.py`. No source code edits are required.

> Note: `railway.json` in this repo configures the **build and deploy**
> settings (Dockerfile-based build, restart policy). Railway does not support
> pre-populating the Variables tab from a plain `railway.json` in a standard
> (non-template) project — you paste the block above once, the first time you
> deploy. If you turn this repo into a Railway **Template** via the Railway
> dashboard's "New Template" flow, you can additionally configure each
> variable there with the same placeholder values so future deployers are
> prompted for them automatically.

### Railway Free/Hobby plan tips

- Keep `MAX_CONCURRENT_DOWNLOADS` at 2–3 to stay within CPU/RAM limits.
- `CACHE_DIR` and `TEMP_DIR` default to `/tmp`, which is ephemeral storage —
  fine for this bot since files are deleted right after upload anyway.
- Large, long videos (2+ hour podcasts/VODs) may approach Railway's per-request
  CPU time on constrained plans; consider lowering `MAX_CONCURRENT_DOWNLOADS`
  to 1 if you see OOM kills in the logs.

---

## Configuration guide

All configuration is environment-variable driven (loaded via `python-dotenv`
locally, or Railway's Variables in production). See `.env.example` for the
full list with defaults. Key variables:

| Variable | Purpose |
|---|---|
| `BOT_TOKEN` | **Required.** Token from @BotFather. |
| `ADMIN_IDS` | Comma-separated numeric Telegram user IDs with admin access (`/stats`, exempt from rate limits). |
| `MAX_FILE_SIZE` | Max upload size in MB; larger files are refused before download. |
| `MAX_CONCURRENT_DOWNLOADS` | How many downloads run at once. |
| `RATE_LIMIT_PER_USER` | Max link submissions per user per 60 seconds. |
| `ALLOWED_DOMAINS` / `BLOCKED_DOMAINS` | Comma-separated domain allow/block lists. `*` allows everything. |
| `COOKIE_FILE` | Path to a Netscape-format cookies file for age-restricted/private content you're authorized to access. |
| `PROXY_URL` | Optional proxy for yt-dlp (e.g. for geo-restricted content). |

The app validates required variables at startup and **exits with a clear,
specific error message** naming the exact missing/invalid variable — it will
never start silently misconfigured.

---

## Troubleshooting

**"Configuration error: BOT_TOKEN is not set"**
You haven't set `BOT_TOKEN` in Railway's Variables tab (or your local `.env`).

**Bot doesn't respond to any links**
Check `ENABLE_AUTO_DETECTION=true` and that the chat type matches
`ENABLE_PRIVATE_CHAT` / `ENABLE_GROUPS` / `ENABLE_SUPERGROUPS`. In groups, make
sure [privacy mode](https://core.telegram.org/bots/features#privacy-mode) is
disabled for your bot via @BotFather (`/setprivacy` → Disable) if you want it
to see all messages, not just commands.

**"This video is age-restricted..."**
Set `COOKIE_FILE` to a cookies.txt file exported from a logged-in browser
session you're authorized to use.

**Downloads fail with a merging/ffmpeg error**
Confirm you deployed using the provided `Dockerfile` (it installs FFmpeg). If
running locally, verify `ffmpeg -version` works in your shell, or set
`FFMPEG_PATH` to the full binary path.

**"exceeds the configured limit" errors**
Raise `MAX_FILE_SIZE` (in MB). Telegram bots cannot upload files larger than
2000 MB regardless of configuration.

**Bot works in DMs but not in a group**
Re-add the bot to the group after disabling privacy mode, or promote it to
admin if the group has restricted permissions for regular members.

---

## Security notes

- All URLs are validated against a strict `http(s)://` pattern and scanned for
  shell metacharacters before being touched.
- Filenames are sanitized and path-joined defensively to prevent traversal
  outside the configured temp directory.
- Every downloaded file is deleted immediately after upload (or on error) via
  a `finally` block.
- Rate limiting and a bounded download queue prevent a single user from
  exhausting server resources.

---

## License

Provided as-is for your own deployment and use. You are responsible for
ensuring your use of yt-dlp and this bot complies with the terms of service
of the platforms you interact with and all applicable law.
