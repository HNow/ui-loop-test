/**
 * Segmentation testing API - runs Phase 1.1 (UIDivision) on uploaded images
 * Returns detected regions with bounding boxes and insights
 */

import { json } from '@sveltejs/kit';
import { exec } from 'child_process';
import { promisify } from 'util';
import { writeFileSync, mkdirSync, existsSync, readFileSync, unlinkSync, readdirSync } from 'fs';
import { join, basename } from 'path';
import { config as loadDotenv } from 'dotenv';

loadDotenv({ path: join(process.cwd(), '.env') });

const execAsync = promisify(exec);

const TEMP_DIR = join(process.cwd(), 'static', 'temp');
const OUTPUT_DIR = join(process.cwd(), 'static', 'output');

function ensureTempDir() {
    if (!existsSync(TEMP_DIR)) {
        mkdirSync(TEMP_DIR, { recursive: true });
    }
}

function ensureOutputDir() {
    if (!existsSync(OUTPUT_DIR)) {
        mkdirSync(OUTPUT_DIR, { recursive: true });
    }
}

/** POST /api/test/segmentation - test segmentation on uploaded image */
export async function POST({ request }) {
    // Check API keys are configured
    if (!process.env.OPENROUTER_API_KEY && !process.env.FIREWORKS_API_KEY) {
        return json({ 
            error: 'No API keys configured. Set OPENROUTER_API_KEY or FIREWORKS_API_KEY environment variable.',
            success: false
        }, { status: 503 });
    }
    
    try {
        const formData = await request.formData();
        const imageFile = formData.get('image');
        
        if (!imageFile || !(imageFile instanceof File)) {
            return json({ error: 'No image file provided' }, { status: 400 });
        }
        
        // Save uploaded image temporarily
        ensureTempDir();
        const timestamp = Date.now();
        const tempImagePath = join(TEMP_DIR, `test_${timestamp}.png`);
        const buffer = Buffer.from(await imageFile.arrayBuffer());
        writeFileSync(tempImagePath, buffer);
        
        // Run Phase 1 segmentation
        ensureOutputDir();
        const testName = `segtest_${timestamp}`;
        
        // Execute the Python script for Phase 1 only using uv
        // Note: main.py's output-dir is the PARENT directory, not the component directory
        const parentOutputDir = join(process.cwd(), 'static');
        const pythonBin = join(process.cwd(), '.venv', 'bin', 'python');
        const command = `cd ${process.cwd()} && ${pythonBin} main.py "${tempImagePath}" --name ${testName} --phase 1 --output-dir ${parentOutputDir}`;
        
        let result;
        try {
            const { stdout, stderr } = await execAsync(command, { timeout: 120000 });
            result = { stdout, stderr, success: true };
        } catch (execError) {
            // Even if command fails partially, we might have results
            result = { 
                stdout: execError.stdout || '', 
                stderr: execError.stderr || '', 
                success: false,
                error: execError.message 
            };
        }
        
        // Read the component output
        let actualOutputDir = null;
        let componentData = null;
        let regionImages = [];
        
        // Try to find the output directory
        if (existsSync(OUTPUT_DIR)) {
            try {
                const dirs = readdirSync(OUTPUT_DIR)
                    .filter(d => d.startsWith(testName))
                    .map(d => join(OUTPUT_DIR, d));
                if (dirs.length > 0) {
                    actualOutputDir = dirs[0];
                    const metaPath = join(actualOutputDir, 'component.json');
                    if (existsSync(metaPath)) {
                        componentData = JSON.parse(readFileSync(metaPath, 'utf-8'));
                    }
                    // Find region images
                    const files = readdirSync(actualOutputDir);
                    regionImages = files
                        .filter(f => f.startsWith('region_') && f.endsWith('.png'))
                        .map(f => `/output/${basename(actualOutputDir)}/${f}`);
                }
            } catch (e) {
                console.error('Error reading output:', e);
            }
        }
        
        // Clean up temp image
        try {
            if (existsSync(tempImagePath)) {
                unlinkSync(tempImagePath);
            }
        } catch (e) {
            console.error('Error cleaning up temp file:', e);
        }
        
        // Calculate insights
        const insights = generateInsights(componentData, result);
        
        return json({
            success: componentData !== null,
            testName,
            component: componentData,
            regionImages,
            insights,
            commandOutput: result.stdout,
            commandError: result.stderr,
            outputDir: actualOutputDir ? `/output/${basename(actualOutputDir)}` : null
        });
        
    } catch (error) {
        console.error('Segmentation test error:', error);
        return json({ 
            error: error.message,
            success: false 
        }, { status: 500 });
    }
}

function generateInsights(componentData, result) {
    const insights = [];
    
    if (!componentData) {
        insights.push({
            type: 'error',
            title: 'Segmentation Failed',
            description: 'Could not parse component data. Check command output for errors.'
        });
        return insights;
    }
    
    const regions = componentData.regions || [];
    
    // Region count insight
    if (regions.length === 0) {
        insights.push({
            type: 'error',
            title: 'No Regions Detected',
            description: 'The segmentation algorithm found no regions. The image may be too simple or the vision model failed to respond.'
        });
    } else if (regions.length < 3) {
        insights.push({
            type: 'warning',
            title: 'Few Regions Detected',
            description: `Only ${regions.length} regions found. The DesignCoder paper recommends 3-10 regions for optimal grouping. Consider using a more complex UI screenshot.`
        });
    } else if (regions.length > 10) {
        insights.push({
            type: 'warning',
            title: 'Many Regions Detected',
            description: `${regions.length} regions found. This may be too granular and could cause issues in Phase 1.3 (Component Grouping).`
        });
    } else {
        insights.push({
            type: 'success',
            title: 'Good Region Count',
            description: `${regions.length} regions detected, which is within the optimal range of 3-10.`
        });
    }
    
    // Region coverage insight
    if (regions.length > 0 && componentData.reference_path) {
        // Calculate total area covered by regions
        // This is a simplified check - in practice we'd use the actual image dimensions
        insights.push({
            type: 'info',
            title: 'Region Coverage',
            description: `${regions.length} semantic regions identified: ${regions.map(r => r.name).join(', ')}`
        });
    }
    
    // Check for common region types
    const regionNames = regions.map(r => r.name.toLowerCase());
    const hasNavigation = regionNames.some(n => n.includes('nav') || n.includes('header'));
    const hasContent = regionNames.some(n => n.includes('content') || n.includes('main') || n.includes('body'));
    const hasFooter = regionNames.some(n => n.includes('footer'));
    
    if (hasNavigation && hasContent) {
        insights.push({
            type: 'success',
            title: 'Standard Layout Detected',
            description: 'Navigation + content structure identified. This is a common and well-supported layout pattern.'
        });
    }
    
    // Check command output for warnings
    if (result.stderr && result.stderr.includes('vision')) {
        insights.push({
            type: 'warning',
            title: 'Vision Model Warning',
            description: 'The vision model reported issues. Results may be less accurate than expected.'
        });
    }
    
    return insights;
}
