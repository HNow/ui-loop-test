/**
 * API for component iterations - server-side only
 */

import { json } from '@sveltejs/kit';
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs';
import { join } from 'path';

const COMPONENTS_DIR = join(process.cwd(), 'static', 'components');

function getComponentDir(id) {
    return join(COMPONENTS_DIR, id);
}

function loadMeta(id) {
    const metaPath = join(getComponentDir(id), 'meta.json');
    if (!existsSync(metaPath)) return null;
    return JSON.parse(readFileSync(metaPath, 'utf-8'));
}

function saveMeta(id, meta) {
    writeFileSync(join(getComponentDir(id), 'meta.json'), JSON.stringify(meta, null, 2));
}

function updateRegistry(id, updates) {
    const registryPath = join(COMPONENTS_DIR, 'registry.json');
    if (!existsSync(registryPath)) return;
    const registry = JSON.parse(readFileSync(registryPath, 'utf-8'));
    const idx = registry.components.findIndex(c => c.id === id);
    if (idx >= 0) {
        registry.components[idx] = { ...registry.components[idx], ...updates };
        writeFileSync(registryPath, JSON.stringify(registry, null, 2));
    }
}

/** GET /api/components/[id] - get component details */
export async function GET({ params }) {
    const { id } = params;
    const meta = loadMeta(id);
    if (!meta) {
        return json({ error: 'Component not found' }, { status: 404 });
    }
    
    // Read current HTML
    const htmlPath = join(getComponentDir(id), 'preview.html');
    const htmlCode = existsSync(htmlPath) 
        ? readFileSync(htmlPath, 'utf-8') 
        : '';
    
    return json({
        ...meta,
        html_code: htmlCode
    });
}

/** POST /api/components/[id] - update component code */
export async function POST({ params, request }) {
    const { id } = params;
    const body = await request.json();
    const { html_code, screenshot, diff, ssim, console_errors, note } = body;
    
    const meta = loadMeta(id);
    if (!meta) {
        return json({ error: 'Component not found' }, { status: 404 });
    }
    
    const compDir = getComponentDir(id);
    const iterNum = meta.iterations.length + 1;
    
    // Save new HTML
    if (html_code) {
        writeFileSync(join(compDir, 'preview.html'), html_code);
        writeFileSync(join(compDir, `v${iterNum}.html`), html_code);
    }
    
    // Save screenshot
    if (screenshot) {
        const screenshotData = screenshot.replace(/^data:image\/\w+;base64,/, '');
        writeFileSync(join(compDir, 'screenshots', `${iterNum}.png`), screenshotData, 'base64');
    }
    
    // Save diff overlay
    if (diff) {
        const diffData = diff.replace(/^data:image\/\w+;base64,/, '');
        writeFileSync(join(compDir, 'diffs', `${iterNum}.png`), diffData, 'base64');
    }
    
    // Update meta
    const iteration = {
        num: iterNum,
        ssim: ssim ?? null,
        has_screenshot: !!screenshot,
        has_diff: !!diff,
        console_errors: console_errors || [],
        note: note || null,
        created_at: new Date().toISOString()
    };
    meta.iterations.push(iteration);
    meta.updated_at = new Date().toISOString();
    
    // Update status
    if (ssim !== null && ssim !== undefined) {
        if (ssim >= 0.88) {
            meta.status = 'done';
        } else if (meta.iterations.length > 5) {
            const recent = meta.iterations.slice(-3).map(i => i.ssim ?? 0);
            if (Math.max(...recent) - Math.min(...recent) < 0.01) {
                meta.status = 'stuck';
            } else {
                meta.status = 'iterating';
            }
        } else {
            meta.status = 'iterating';
        }
    }
    
    saveMeta(id, meta);
    
    // Update registry
    const bestSsim = meta.iterations.length > 0 
        ? Math.max(...meta.iterations.map(i => i.ssim ?? 0)) 
        : null;
    updateRegistry(id, {
        status: meta.status,
        iteration_count: meta.iterations.length,
        best_ssim: bestSsim,
        updated_at: meta.updated_at
    });
    
    return json({ success: true, iteration, meta });
}

/** PATCH /api/components/[id] - update status or notes */
export async function PATCH({ params, request }) {
    const { id } = params;
    const updates = await request.json();
    
    const meta = loadMeta(id);
    if (!meta) {
        return json({ error: 'Component not found' }, { status: 404 });
    }
    
    Object.assign(meta, updates, { updated_at: new Date().toISOString() });
    saveMeta(id, meta);
    
    if (updates.status) {
        updateRegistry(id, { status: updates.status, updated_at: meta.updated_at });
    }
    
    return json({ success: true, meta });
}

/** DELETE /api/components/[id] - delete component */
export async function DELETE({ params }) {
    const { id } = params;
    updateRegistry(id, { status: 'deleted' });
    return json({ success: true });
}
