import { error } from '@sveltejs/kit';
import { readFileSync, existsSync } from 'fs';
import { join } from 'path';

const COMPONENTS_DIR = join(process.cwd(), 'static', 'components');

export async function load({ params }) {
    const { id } = params;
    const metaPath = join(COMPONENTS_DIR, id, 'meta.json');
    
    if (!existsSync(metaPath)) {
        throw error(404, 'Component not found');
    }

    const meta = JSON.parse(readFileSync(metaPath, 'utf-8'));
    
    // Read current HTML code
    const htmlPath = join(COMPONENTS_DIR, id, 'preview.html');
    const htmlCode = existsSync(htmlPath) 
        ? readFileSync(htmlPath, 'utf-8') 
        : '';

    return {
        id,
        meta,
        htmlCode
    };
}
