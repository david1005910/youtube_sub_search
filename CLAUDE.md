# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This project is a specification for a **YouTube Content Material Discovery Tool** (유튜브 소재 발굴 도구). The file `소재찾기.docx` contains a detailed AI prompt that generates a complete, runnable single-file web application.

## Target Output

The goal is to produce a single `index.html` file that can be opened directly in a browser with no build step.

## Tech Stack

- **HTML5 / CSS3 / Vanilla JavaScript** — no frameworks, no bundler
- **Tailwind CSS** via CDN
- **YouTube Data API v3** — video search, video details (view count), channel details (subscriber count)
- **Gemini 1.5 Flash** (`gemini-1.5-flash`) via Google AI SDK (ES module import)

## Core Architecture

All logic lives in one file. The key layers are:

1. **API config block** — `YOUTUBE_API_KEY` and `GEMINI_API_KEY` constants at the top of the `<script>` tag, with comments directing the user to replace them.

2. **Search & filter pipeline**
   - Keyword → YouTube Search API → list of video IDs
   - Batch fetch video details (view count) and channel details (subscriber count)
   - Compute **View-to-Sub Ratio** = `(views / subscribers) * 100` for each result
   - Sort results descending by ratio (high ratio = strong content angle)

3. **Comment collection** — triggered per-video via a "댓글 분석" button; fetches top 50 comments for that video.

4. **Gemini analysis** — sends video title + collected comments to Gemini 1.5 Flash and returns:
   - Positive viewer reactions
   - Pain points / unanswered questions
   - 3 next-video ideas with specific production directions

5. **UI** — dark-mode, card-based results with loading spinners; cards link out to the YouTube video.

## API Key Setup

When generating or editing the HTML file, the two keys the user must supply are:

- **YouTube Data API v3**: Google Cloud Console → create project → enable "YouTube Data API v3" → Credentials → API key
- **Gemini API key**: Google AI Studio (free tier available)

## API Quota Considerations

YouTube Data API v3 has a daily quota (10,000 units by default). Each search costs 100 units; video/channel detail fetches cost 1–3 units each. Batch video/channel calls to minimize quota usage.
