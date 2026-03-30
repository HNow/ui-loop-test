/**
 * POST /api/components/:id/feedback
 *
 * Body: {
 *   query:    string,
 *   elements: Array<{tagName, id, classes, text, rect, styles}>,
 *   crops:    Array<{label: 'reference'|'snapshot', dataUrl: string, rect: object}>
 * }
 *
 * Saves to static/components/{id}/feedback/fb_{timestamp}/
 *   query.txt          — raw user query
 *   elements.json      — selected DOM elements
 *   crop_N_label.png   — cropped image regions
 *   context.json       — full summary for agent consumption
 */

import { json } from '@sveltejs/kit';
import { writeFileSync, mkdirSync, existsSync } from 'fs';
import { join } from 'path';

const COMPONENTS_DIR = join(process.cwd(), 'static', 'components');

export async function POST({ params, request }) {
    const { id } = params;
    const compDir = join(COMPONENTS_DIR, id);

    if (!existsSync(compDir)) {
        return json({ error: `Component ${id} not found` }, { status: 404 });
    }

    const body = await request.json();
    const { query = '', elements = [], crops = [] } = body;

    const ts = Date.now();
    const folderName = `fb_${ts}`;
    const fbDir = join(compDir, 'feedback', folderName);
    mkdirSync(fbDir, { recursive: true });

    // query.txt
    if (query.trim()) {
        writeFileSync(join(fbDir, 'query.txt'), query.trim(), 'utf-8');
    }

    // elements.json
    if (elements.length > 0) {
        writeFileSync(join(fbDir, 'elements.json'), JSON.stringify(elements, null, 2), 'utf-8');
    }

    // crop images
    const savedCrops = [];
    crops.forEach((crop, i) => {
        try {
            const filename = `crop_${i}_${crop.label}.png`;
            const b64 = crop.dataUrl.replace(/^data:image\/\w+;base64,/, '');
            writeFileSync(join(fbDir, filename), Buffer.from(b64, 'base64'));
            savedCrops.push({ file: filename, label: crop.label, rect: crop.rect });
        } catch (e) {
            console.error(`Failed to save crop ${i}:`, e);
        }
    });

    // context.json — structured summary an agent can parse directly
    const context = {
        component_id: id,
        created_at: new Date(ts).toISOString(),
        folder: `feedback/${folderName}`,
        component_path: `static/components/${id}/`,
        preview_html: `static/components/${id}/preview.html`,
        query: query.trim() || null,
        selected_elements: elements,
        image_crops: savedCrops,
        instructions: [
            'Read query.txt for the user\'s feedback.',
            'elements.json contains selected DOM elements with computed styles and bounding boxes.',
            'Each crop_N_*.png is a region the user highlighted — label indicates source (reference or snapshot).',
            'Read preview.html for the current component source to apply fixes.',
        ],
    };
    writeFileSync(join(fbDir, 'context.json'), JSON.stringify(context, null, 2), 'utf-8');

    return json({ ok: true, folder: folderName, path: fbDir });
}
