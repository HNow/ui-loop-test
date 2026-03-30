/**
 * Filesystem-derived event stream for the activity feed.
 *
 * Uses file mtimes as ground truth — works regardless of how the agent
 * writes files (CLI tools, direct writes, bash one-liners, etc.).
 *
 * Also merges any log.ndjson events written by loop.py (Python path).
 *
 * GET ?since=<timestamp_ms>  →  { events: [...], next: <timestamp_ms> }
 *
 * Client starts with since=0 to load all history, then passes the returned
 * `next` value on each subsequent poll.
 */

import { json } from '@sveltejs/kit';
import { readFileSync, existsSync, statSync, readdirSync } from 'fs';
import { join } from 'path';

const COMPONENTS_DIR = join(process.cwd(), 'static', 'components');

export async function GET({ params, url }) {
    const { id } = params;
    const since = parseInt(url.searchParams.get('since') || '0');
    const compDir = join(COMPONENTS_DIR, id);

    if (!existsSync(compDir)) {
        return json({ events: [], next: since });
    }

    const events = [];

    // ── preview.html ───────────────────────────────────────────────────────────
    const previewPath = join(compDir, 'preview.html');
    if (existsSync(previewPath)) {
        const mtime = statSync(previewPath).mtimeMs;
        if (mtime > since) {
            events.push({
                type: 'html_written',
                ts: new Date(mtime).toISOString(),
                mtime,
            });
        }
    }

    // ── screenshots/{n}.png ───────────────────────────────────────────────────
    const screenshotsDir = join(compDir, 'screenshots');
    if (existsSync(screenshotsDir)) {
        readdirSync(screenshotsDir)
            .filter(f => /^\d+\.png$/.test(f))
            .map(f => {
                const mtime = statSync(join(screenshotsDir, f)).mtimeMs;
                return { file: f, num: parseInt(f), mtime };
            })
            .filter(f => f.mtime > since)
            .sort((a, b) => a.num - b.num)
            .forEach(f => events.push({
                type: 'screenshot',
                ts: new Date(f.mtime).toISOString(),
                mtime: f.mtime,
                num: f.num,
                path: `/components/${id}/screenshots/${f.file}`,
            }));
    }

    // ── diffs/{n}.png ─────────────────────────────────────────────────────────
    const diffsDir = join(compDir, 'diffs');
    if (existsSync(diffsDir)) {
        readdirSync(diffsDir)
            .filter(f => /^\d+\.png$/.test(f))
            .map(f => {
                const mtime = statSync(join(diffsDir, f)).mtimeMs;
                return { file: f, num: parseInt(f), mtime };
            })
            .filter(f => f.mtime > since)
            .sort((a, b) => a.num - b.num)
            .forEach(f => events.push({
                type: 'diff',
                ts: new Date(f.mtime).toISOString(),
                mtime: f.mtime,
                num: f.num,
                path: `/components/${id}/diffs/${f.file}`,
            }));
    }

    // ── screenshots/current.png (live render) ─────────────────────────────────
    const currentPath = join(screenshotsDir, 'current.png');
    if (existsSync(currentPath)) {
        const mtime = statSync(currentPath).mtimeMs;
        if (mtime > since) {
            events.push({
                type: 'current_render',
                ts: new Date(mtime).toISOString(),
                mtime,
                path: `/components/${id}/screenshots/current.png`,
            });
        }
    }

    // ── meta.json (iteration data) ────────────────────────────────────────────
    const metaPath = join(compDir, 'meta.json');
    if (existsSync(metaPath)) {
        const mtime = statSync(metaPath).mtimeMs;
        if (mtime > since) {
            try {
                const meta = JSON.parse(readFileSync(metaPath, 'utf-8'));
                const latest = meta.iterations[meta.iterations.length - 1] ?? null;
                events.push({
                    type: 'meta_update',
                    ts: new Date(mtime).toISOString(),
                    mtime,
                    status: meta.status,
                    iteration_count: meta.iterations.length,
                    latest_iter: latest,
                });
            } catch { /* malformed mid-write — skip */ }
        }
    }

    // ── log.ndjson (Python loop.py path — richer events when available) ────────
    const logPath = join(compDir, 'log.ndjson');
    if (existsSync(logPath)) {
        const content = readFileSync(logPath, 'utf-8');
        content.split('\n').filter(Boolean).forEach(line => {
            try {
                const ev = JSON.parse(line);
                const evMs = new Date(ev.ts).getTime();
                if (evMs > since) {
                    events.push({ ...ev, mtime: evMs });
                }
            } catch { /* skip malformed */ }
        });
    }

    // Sort all events chronologically
    events.sort((a, b) => a.mtime - b.mtime);

    // next = latest event mtime + 1 (so next poll only sees newer changes)
    const next = events.length > 0
        ? Math.max(...events.map(e => e.mtime)) + 1
        : since;

    return json({ events, next });
}
