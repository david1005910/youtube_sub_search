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
The server reads/writes `.env` for key persistence and proxies Gemini Imagen, TranscriptAPI, and ComfyUI calls to avoid CORS.

**Subtitle render server** (optional — needed for the 🎞️ widget):
```bash
cd remotion && npm start   # starts at http://localhost:8766
```

## Architecture

### `index.html` — the entire frontend (~2,934 lines, single file)

All logic is vanilla JS ES modules with Tailwind CSS (CDN). Key sections in order:

1. **CSS block** — dark-mode styles, spinner, ratio bar, script-section cards, five floating widget styles
2. **HTML layout** — viral-ratio explainer panel → API key inputs → search filters → results grid
3. **JavaScript** — one large `<script type="module">` at the bottom

Key JS functions and their roles:

| Function | Role |
|---|---|
| `loadConfig()` / `saveConfig()` | Fetch from `GET/POST /api/config` when server mode; falls back to sessionStorage |
| `searchVideos()` | `youtube.search.list` with duration/period filters |
| `fetchVideosWithChannels()` | Batch `youtube.videos.list` + `youtube.channels.list`; builds channel subscriber map |
| `combineAndSort()` | Computes `viralRatio = views/subs*100`, sorts descending |
| `renderResults()` | Renders result cards into `#results` grid |
| `startCommentAnalysis()` | Entry point for per-video comment collection + Gemini analysis modal |
| `callGeminiAnalysis()` | First Gemini call — reactions, pain points, top-5 keywords, viral scores, 5 topic suggestions |
| `callGeminiOutline()` | Second Gemini call — full script outline (title candidates, thumbnail, hook, chapters, CTA) |
| `geminiChat()` | Multi-turn chat using `generateContent` with `contents` history array |
| `openGrokModal()` / Imagen section | Image generation modal (named `grokModal` in HTML — legacy name from before Grok→Gemini switch) |
| `initSubtitleRenderWidget()` | Subtitle burn-in widget; checks remotion server health on open |
| `initYtChatBindings()` | Green YouTube Creator AI chat widget event wiring |
| `initYtApiChatBindings()` | Blue TranscriptAPI chat widget event wiring |

**Five floating widgets** (fixed-position, bottom-right, left to right):
- Red/Brown `#comfyToggle` (right: 288px) — ComfyUI video generation widget (proxies to ComfyUI at `COMFY_URL`)
- Orange `#subtitleRenderToggle` (right: 222px) — subtitle burn-in widget (connects to remotion render server at :8766)
- Blue `#ytApiChatToggle` (right: 156px) — YouTube TranscriptAPI chat (youtube-skills-main skills)
- Green `#ytChatToggle` (right: 90px) — YouTube Creator AI (claude-youtube-main skills)
- Purple `#scriptImgChatToggle` (right: 24px) — image-based script chat (Gemini multimodal)

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
| `POST /api/proxy/gemini-image` | Proxy to Gemini Imagen API (avoids CORS; uses `GEMINI_API_KEY`) |
| `GET /api/proxy/comfy*` | Proxy GET requests to ComfyUI (system_stats, history, view, queue, object_info) |
| `POST /api/proxy/comfy/prompt` | Proxy workflow submission to ComfyUI |

All other paths are served as static files from the project root.

### Skill directories

- `claude-youtube-main/` — YouTube Creator AI skill (14 sub-skills under `skills/claude-youtube/sub-skills/`)
- `youtube-skills-main/` — TranscriptAPI-based skills (transcript, playlist, channel, search, subtitles, etc. — each in `skills/<name>/SKILL.md`)

### `remotion/` — subtitle burn-in renderer

Remotion 4.0.457 + Express render server. Source files are implemented:
- `src/Root.tsx` — Remotion composition root
- `src/SubtitleOverlay.tsx` — subtitle overlay component
- `render-server.mjs` — Express server at `:8766` with `POST /render` (accepts video path + subtitle segments, returns MP4) and `GET /health`

Start with `cd remotion && npm start`.

## API Keys (stored in `.env`)

| Key | Used for |
|---|---|
| `YOUTUBE_API_KEY` | YouTube Data API v3 (search, videos, channels, comments) |
| `GEMINI_API_KEY` | Gemini AI (comment analysis, script generation, image chat, Imagen 4) |
| `GEMINI_MODEL` | Model name, default `gemini-2.5-flash` |
| `TRANSCRIPT_API_KEY` | transcriptapi.com (TranscriptAPI chat widget + subtitle widget) |
| `COMFY_URL` | ComfyUI base URL, default `http://localhost:8188` |
| `XAI_API_KEY` | Reserved (stored in `.env` but not currently wired to any active feature) |

## API Quota

YouTube Data API v3: 10,000 units/day free. One full search costs ~200–300 units (100 search + ~1–3/video + ~1/channel).

## Key Metrics

**Viral Ratio** = `(views ÷ subscribers) × 100`. The main sort key. ≥200% = verified material, ≥500% = strong viral, ≥1000% = algorithm explosion.
