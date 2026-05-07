/**
 * Subtitle burn-in render server — http://localhost:8766
 *
 * POST /render
 *   Body (JSON):
 *     videoSrc           string   — absolute local path or https:// URL
 *     subtitles          Segment[] — [{ text, start, duration }]  (original language)
 *     translatedSubtitles Segment[] — bilingual overlay (optional)
 *     fps                number   — default 30
 *     width              number   — default 1920
 *     height             number   — default 1080
 *     durationInSeconds  number   — required; total video length
 *
 *   Response: MP4 file download (output deleted after transfer)
 *
 * GET /health  →  { ok: true }
 */

import express from 'express';
import { bundle } from '@remotion/bundler';
import { renderMedia, selectComposition } from '@remotion/renderer';
import { createRequire } from 'module';
import { fileURLToPath } from 'url';
import path from 'path';
import fs from 'fs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);

const app = express();
app.use(express.json({ limit: '50mb' }));

app.use((_req, res, next) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (_req.method === 'OPTIONS') { res.sendStatus(200); return; }
  next();
});

const OUTPUT_DIR = path.join(__dirname, 'output');
fs.mkdirSync(OUTPUT_DIR, { recursive: true });

let bundleCache = null;

async function getBundle() {
  if (!bundleCache) {
    console.log('Bundling Remotion composition (first run, ~30s)…');
    bundleCache = await bundle({
      entryPoint: path.join(__dirname, 'src/Root.tsx'),
      webpackOverride: (config) => config,
    });
    console.log('Bundle ready.');
  }
  return bundleCache;
}

app.get('/health', (_req, res) => res.json({ ok: true }));

app.post('/render', async (req, res) => {
  const {
    videoSrc,
    subtitles = [],
    translatedSubtitles = [],
    fps = 30,
    width = 1920,
    height = 1080,
    durationInSeconds,
  } = req.body;

  if (!videoSrc) return res.status(400).json({ error: 'videoSrc is required' });
  if (!durationInSeconds) return res.status(400).json({ error: 'durationInSeconds is required' });

  const durationInFrames = Math.ceil(durationInSeconds * fps);
  const outputPath = path.join(OUTPUT_DIR, `subtitle-${Date.now()}.mp4`);

  try {
    const serveUrl = await getBundle();

    const composition = await selectComposition({
      serveUrl,
      id: 'SubtitleOverlay',
      inputProps: { videoSrc, subtitles, translatedSubtitles },
    });

    // Override timing from request
    composition.durationInFrames = durationInFrames;
    composition.fps = fps;
    composition.width = width;
    composition.height = height;

    await renderMedia({
      composition,
      serveUrl,
      codec: 'h264',
      outputLocation: outputPath,
      inputProps: { videoSrc, subtitles, translatedSubtitles },
      onProgress: ({ progress }) => {
        process.stdout.write(`\rRendering… ${(progress * 100).toFixed(1)}%`);
      },
    });

    console.log(`\nDone → ${outputPath}`);
    res.download(outputPath, `subtitled-${Date.now()}.mp4`, () => {
      fs.unlink(outputPath, () => {});
    });
  } catch (err) {
    console.error(err);
    fs.unlink(outputPath, () => {});
    res.status(500).json({ error: String(err) });
  }
});

const PORT = 8766;
app.listen(PORT, () => {
  console.log(`✅ Subtitle renderer → http://localhost:${PORT}`);
  console.log('   POST /render  |  GET /health');
  console.log('   종료: Ctrl+C');
});
