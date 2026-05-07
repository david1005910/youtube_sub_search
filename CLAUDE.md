# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A **YouTube Content Material Discovery Tool** (유튜브 소재 발굴 도구) — a single-file web app that finds high-viral-ratio YouTube videos, collects comments, and runs Gemini AI analysis to generate script outlines.

## Running the App

Two modes:

**Direct browser** (no server): open `index.html` directly. API keys must be entered in the UI on every session (not persisted).

**Local server** (recommended — persists API keys via `.env`):
```bash
python3 server.py        # starts at http://localhost:8765
```
The server reads/writes `.env` for key persistence and proxies TranscriptAPI calls to avoid CORS.

## Architecture

### `index.html` — the entire frontend (~87 KB, single file)

All logic is vanilla JS ES modules with Tailwind CSS (CDN). Key sections in order:

1. **CSS block** — dark-mode styles, spinner, ratio bar, script-section cards, three chat widget styles
2. **HTML layout** — viral-ratio explainer panel → API key inputs → search filters → results grid
3. **JavaScript** — one large `<script type="module">` at the bottom:
   - `loadConfig()` / `saveConfig()` — fetch from `GET/POST /api/config` when server mode; falls back to sessionStorage
   - **Search pipeline**: keyword → `youtube.search.list` → batch `youtube.videos.list` (view count) + `youtube.channels.list` (subscriber count) → compute `viralRatio = views/subs*100` → sort descending
   - **Comment analysis**: per-video `youtube.commentThreads.list` (top 50) → Gemini prompt → returns reactions, pain points, top-5 keywords, viral-factor scores, and 5 topic suggestions
   - **Script generation**: user picks a topic + word count → second Gemini call → structured outline with title candidates, thumbnail concept, hook, chapters, CTA
   - **Three chat widgets** (fixed-position floating buttons, bottom-right):
     - Purple `#scriptImgChatToggle` — image-based script chat (Gemini multimodal)
     - Green `#ytChatToggle` — YouTube Creator AI (claude-youtube-main skills)
     - Blue `#ytApiChatToggle` — YouTube TranscriptAPI chat (youtube-skills-main skills)

### `server.py` — lightweight Python HTTP server

Extends `SimpleHTTPRequestHandler`. API endpoints:

| Route | Purpose |
|---|---|
| `GET /api/config` | Return `.env` key values |
| `POST /api/config` | Persist keys to `.env` |
| `GET /api/skills` | List claude-youtube-main sub-skills |
| `GET /api/skill/<name>` | Return SKILL.md content for a sub-skill |
| `GET /api/yt-skills` | List youtube-skills-main skills |
| `GET /api/yt-skill/<name>` | Return SKILL.md content |
| `POST /api/proxy/transcriptapi` | Proxy to transcriptapi.com (requires `TRANSCRIPT_API_KEY`) |

All other paths are served as static files from the project root.

### Skill directories

- `claude-youtube-main/` — YouTube Creator AI skill (14 sub-skills under `skills/claude-youtube/sub-skills/`)
- `youtube-skills-main/` — TranscriptAPI-based skills (transcript, playlist, channel, search, subtitles, etc.)

### `remotion/` — subtitle renderer (stub)

`package.json` is present (`subtitle-renderer`, Remotion 4.0.457 + Express). No source files yet — this is a planned video subtitle burn-in feature. Run with `node render-server.mjs` once source is added.

## API Keys (stored in `.env`)

| Key | Used for |
|---|---|
| `YOUTUBE_API_KEY` | YouTube Data API v3 (search, videos, channels, comments) |
| `GEMINI_API_KEY` | Gemini AI (comment analysis, script generation, image chat) |
| `GEMINI_MODEL` | Model name, default `gemini-2.5-flash` |
| `TRANSCRIPT_API_KEY` | transcriptapi.com (TranscriptAPI chat widget) |

## API Quota

YouTube Data API v3: 10,000 units/day free. One full search costs ~200–300 units (100 search + ~1–3/video + ~1/channel).

## Key Metrics

**Viral Ratio** = `(views ÷ subscribers) × 100`. The main sort key. ≥200% = verified material, ≥500% = strong viral, ≥1000% = algorithm explosion.
