/**
 * Component registry API - server-side only
 */

import { json } from '@sveltejs/kit';
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs';
import { join } from 'path';

const COMPONENTS_DIR = join(process.cwd(), 'static', 'components');
const REGISTRY_PATH = join(COMPONENTS_DIR, 'registry.json');

function ensureDir() {
    if (!existsSync(COMPONENTS_DIR)) {
        mkdirSync(COMPONENTS_DIR, { recursive: true });
    }
}

function loadRegistry() {
    ensureDir();
    if (!existsSync(REGISTRY_PATH)) {
        writeFileSync(REGISTRY_PATH, JSON.stringify({ components: [] }, null, 2));
    }
    return JSON.parse(readFileSync(REGISTRY_PATH, 'utf-8'));
}

function saveRegistry(registry) {
    ensureDir();
    writeFileSync(REGISTRY_PATH, JSON.stringify(registry, null, 2));
}

/** GET /api/components - list all components */
export async function GET() {
    const registry = loadRegistry();
    return json(registry);
}

/** POST /api/components - create new component */
export async function POST({ request }) {
    const body = await request.json();
    const { name, reference } = body;
    const id = `comp_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    
    ensureDir();
    const compDir = join(COMPONENTS_DIR, id);
    mkdirSync(compDir, { recursive: true });
    mkdirSync(join(compDir, 'screenshots'), { recursive: true });
    mkdirSync(join(compDir, 'diffs'), { recursive: true });
    
    // Copy reference image if provided
    let refFilename = null;
    if (reference && existsSync(reference)) {
        const ext = reference.split('.').pop();
        const refDest = join(compDir, `reference.${ext}`);
        writeFileSync(refDest, readFileSync(reference));
        refFilename = `reference.${ext}`;
    }
    
    // Create initial preview.html
    writeFileSync(join(compDir, 'preview.html'), `<!DOCTYPE html>
<html>
<head>
  <style>
    body { margin: 0; padding: 2rem; background: #fff; font-family: system-ui; }
    .placeholder { color: #999; text-align: center; padding: 4rem; }
  </style>
</head>
<body>
  <div class="placeholder">
    <p>Component not yet generated</p>
  </div>
</body>
</html>
`);
    
    // Create meta.json
    const meta = {
        id,
        name,
        reference: refFilename,
        status: 'initial',
        iterations: [],
        colors: [],
        scratchpad: '',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString()
    };
    writeFileSync(join(compDir, 'meta.json'), JSON.stringify(meta, null, 2));
    
    // Update registry
    const registry = loadRegistry();
    registry.components.push({
        id,
        name,
        status: 'initial',
        iteration_count: 0,
        best_ssim: null,
        updated_at: meta.updated_at
    });
    saveRegistry(registry);
    
    return json({ success: true, id, path: compDir });
}
