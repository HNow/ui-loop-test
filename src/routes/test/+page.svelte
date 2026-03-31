<script>
  import { onMount } from 'svelte';
  
  // Tab state
  let activeTab = 'segmentation'; // 'segmentation' | 'extraction' | 'grouping' | 'full'
  
  // Segmentation test state
  let selectedFile = null;
  let previewUrl = null;
  let isProcessing = false;
  let testResult = null;
  let testError = null;
  
  // Handle file selection
  function handleFileSelect(event) {
    const file = event.target.files[0];
    if (file && file.type.startsWith('image/')) {
      selectedFile = file;
      previewUrl = URL.createObjectURL(file);
      testResult = null;
      testError = null;
    }
  }
  
  // Run segmentation test
  async function runSegmentationTest() {
    if (!selectedFile) return;
    
    isProcessing = true;
    testError = null;
    testResult = null;
    
    try {
      const formData = new FormData();
      formData.append('image', selectedFile);
      
      const res = await fetch('/api/test/segmentation', {
        method: 'POST',
        body: formData
      });
      
      const data = await res.json();
      
      if (!data.success) {
        testError = data.error || 'Segmentation failed';
      } else {
        testResult = data;
      }
    } catch (e) {
      testError = e.message;
    } finally {
      isProcessing = false;
    }
  }
  
  // Clear results
  function clearResults() {
    selectedFile = null;
    previewUrl = null;
    testResult = null;
    testError = null;
  }
  
  // Get insight icon/color
  function insightStyle(type) {
    switch (type) {
      case 'success': return { color: '#22c55e', icon: '✓' };
      case 'warning': return { color: '#f59e0b', icon: '⚠' };
      case 'error': return { color: '#ef4444', icon: '✗' };
      default: return { color: '#3b82f6', icon: 'ℹ' };
    }
  }
  
  // Color palette for regions (matches the overlay colors)
  const REGION_COLORS = [
    '#3b82f6', // blue
    '#22c55e', // green  
    '#f59e0b', // yellow
    '#ef4444', // red
    '#8b5cf6', // purple
    '#ec4899', // pink
    '#06b6d4', // cyan
    '#84cc16', // lime
    '#f97316', // orange
    '#14b8a6', // teal
  ];
  
  function getRegionColor(index) {
    return REGION_COLORS[index % REGION_COLORS.length];
  }
</script>

<svelte:head>
  <title>Feature Testing - UI Cloner</title>
</svelte:head>

<div class="root">
  <header>
    <div class="header-content">
      <h1>Feature Testing</h1>
      <p class="sub">Test individual pipeline phases and inspect results</p>
    </div>
    <a href="/" class="back-btn">← Back to Components</a>
  </header>

  <!-- Tabs -->
  <nav class="tabs">
    <button 
      class="tab" 
      class:active={activeTab === 'segmentation'}
      onclick={() => activeTab = 'segmentation'}
    >
      Phase 1.1: Segmentation
    </button>
    <button 
      class="tab" 
      class:active={activeTab === 'extraction'}
      onclick={() => activeTab = 'extraction'}
      disabled
      title="Coming soon"
    >
      Phase 1.2: Extraction
    </button>
    <button 
      class="tab" 
      class:active={activeTab === 'grouping'}
      onclick={() => activeTab = 'grouping'}
      disabled
      title="Coming soon"
    >
      Phase 1.3: Grouping
    </button>
    <button 
      class="tab" 
      class:active={activeTab === 'full'}
      onclick={() => activeTab = 'full'}
      disabled
      title="Coming soon"
    >
      Full Pipeline
    </button>
  </nav>

  <!-- Segmentation Tab -->
  {#if activeTab === 'segmentation'}
    <div class="tab-content">
      <div class="panel">
        <h2>Phase 1.1: UI Division (Segmentation)</h2>
        <p class="description">
          Test the semantic region segmentation. Upload a UI screenshot and see how the 
          algorithm partitions it into 3-10 semantic regions (navigation, hero, content, etc.).
        </p>
        
        <!-- Upload Area -->
        <div class="upload-section">
          {#if !previewUrl}
            <label class="upload-area">
              <input 
                type="file" 
                accept="image/*" 
                onchange={handleFileSelect}
                style="display: none;"
              />
              <div class="upload-prompt">
                <span class="upload-icon">📤</span>
                <p>Click to upload a UI screenshot</p>
                <p class="hint">PNG, JPG, WebP supported</p>
              </div>
            </label>
          {:else}
            <div class="preview-container">
              <img src={previewUrl} alt="Preview" class="preview-image" />
              <button class="clear-btn" onclick={clearResults}>✕ Remove</button>
            </div>
          {/if}
        </div>

        <!-- Action Button -->
        {#if previewUrl}
          <div class="actions">
            <button 
              class="run-btn" 
              onclick={runSegmentationTest}
              disabled={isProcessing}
            >
              {#if isProcessing}
                <span class="spinner"></span> Processing...
              {:else}
                🔍 Run Segmentation
              {/if}
            </button>
          </div>
        {/if}

        <!-- Error Display -->
        {#if testError}
          <div class="error-panel">
            <h3>❌ Error</h3>
            <p>{testError}</p>
          </div>
        {/if}

        <!-- Results -->
        {#if testResult}
          <div class="results">
            <h3>📊 Segmentation Results</h3>
            
            <!-- Insights Panel -->
            {#if testResult.insights && testResult.insights.length > 0}
              <div class="insights-panel">
                <h4>💡 Insights</h4>
                {#each testResult.insights as insight}
                  {@const style = insightStyle(insight.type)}
                  <div class="insight" style="border-left-color: {style.color}">
                    <span class="insight-icon" style="color: {style.color}">{style.icon}</span>
                    <div class="insight-content">
                      <strong style="color: {style.color}">{insight.title}</strong>
                      <p>{insight.description}</p>
                    </div>
                  </div>
                {/each}
              </div>
            {/if}

            <!-- Visual Overlay -->
            {#if testResult.component && testResult.component.regions && previewUrl}
              <div class="overlay-section">
                <h4>🎨 Visual Region Map</h4>
                <div class="overlay-container">
                  <img src={previewUrl} alt="Original" class="overlay-base" />
                  {#each testResult.component.regions as region, i}
                    <div 
                      class="region-overlay"
                      style="
                        left: {region.bbox[0]}px;
                        top: {region.bbox[1]}px;
                        width: {region.bbox[2]}px;
                        height: {region.bbox[3]}px;
                        border-color: {getRegionColor(i)};
                      "
                    >
                      <span class="overlay-label" style="background: {getRegionColor(i)}">
                        {i + 1}: {region.name}
                      </span>
                    </div>
                  {/each}
                </div>
                <p class="overlay-hint">
                  Hover over regions to see boundaries. Colors match the region cards below.
                </p>
              </div>
            {/if}

            <!-- Regions Grid -->
            {#if testResult.component && testResult.component.regions}
              <div class="regions-section">
                <h4>🗂️ Detected Regions ({testResult.component.regions.length})</h4>
                <div class="regions-grid">
                  {#each testResult.component.regions as region, i}
                    <div class="region-card" style="border-color: {getRegionColor(i)}40">
                      <div class="region-header">
                        <span class="region-num" style="background: {getRegionColor(i)}">{i + 1}</span>
                        <span class="region-name">{region.name}</span>
                      </div>
                      <div class="region-bbox">
                        📐 {region.bbox[0]}, {region.bbox[1]} | {region.bbox[2]}×{region.bbox[3]}px
                      </div>
                      {#if testResult.regionImages[i]}
                        <img 
                          src={testResult.regionImages[i]} 
                          alt="Region {i + 1}" 
                          class="region-thumb"
                          onerror={(e) => e.target.style.display = 'none'}
                        />
                      {/if}
                    </div>
                  {/each}
                </div>
              </div>
            {/if}

            <!-- Raw JSON Toggle -->
            <details class="raw-data">
              <summary>📄 View Raw Component Data</summary>
              <pre>{JSON.stringify(testResult.component, null, 2)}</pre>
            </details>

            <!-- Command Output -->
            {#if testResult.commandOutput}
              <details class="raw-data">
                <summary>🖥️ Command Output</summary>
                <pre class="command-output">{testResult.commandOutput}</pre>
              </details>
            {/if}
          </div>
        {/if}
      </div>
    </div>
  {/if}

  <!-- Other tabs (placeholder) -->
  {#if activeTab !== 'segmentation'}
    <div class="tab-content">
      <div class="panel placeholder">
        <p>🚧 This feature is coming soon.</p>
        <p class="hint">Currently only Phase 1.1 (Segmentation) is implemented for testing.</p>
      </div>
    </div>
  {/if}
</div>

<style>
  :global(body) {
    margin: 0;
    background: #0a0a0b;
    color: #e2e2e8;
    font-family: 'Inter', system-ui, sans-serif;
  }

  .root {
    max-width: 1200px;
    margin: 0 auto;
    padding: 2rem 1.5rem;
  }

  header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 2rem;
  }

  h1 {
    font-size: 2rem;
    font-weight: 600;
    margin: 0 0 0.25rem;
    letter-spacing: -0.03em;
  }

  .sub {
    color: #666;
    margin: 0;
  }

  .back-btn {
    color: #666;
    text-decoration: none;
    padding: 0.5rem 1rem;
    border: 1px solid #333;
    border-radius: 6px;
    transition: all 0.15s;
  }

  .back-btn:hover {
    color: #e2e2e8;
    border-color: #555;
  }

  /* Tabs */
  .tabs {
    display: flex;
    gap: 0.5rem;
    border-bottom: 1px solid #222;
    margin-bottom: 2rem;
    overflow-x: auto;
  }

  .tab {
    padding: 0.75rem 1.25rem;
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: #666;
    font-size: 0.9rem;
    cursor: pointer;
    transition: all 0.15s;
    white-space: nowrap;
  }

  .tab:hover:not(:disabled) {
    color: #e2e2e8;
  }

  .tab.active {
    color: #3b82f6;
    border-bottom-color: #3b82f6;
  }

  .tab:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  /* Tab Content */
  .tab-content {
    animation: fadeIn 0.2s ease;
  }

  @keyframes fadeIn {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
  }

  .panel {
    background: #111113;
    border: 1px solid #222;
    border-radius: 12px;
    padding: 2rem;
  }

  .panel h2 {
    margin: 0 0 0.5rem;
    font-size: 1.4rem;
  }

  .description {
    color: #888;
    margin: 0 0 2rem;
    line-height: 1.6;
  }

  /* Upload Area */
  .upload-section {
    margin-bottom: 1.5rem;
  }

  .upload-area {
    display: block;
    border: 2px dashed #333;
    border-radius: 12px;
    padding: 3rem 2rem;
    text-align: center;
    cursor: pointer;
    transition: all 0.15s;
  }

  .upload-area:hover {
    border-color: #3b82f6;
    background: rgba(59, 130, 246, 0.05);
  }

  .upload-icon {
    font-size: 2.5rem;
    display: block;
    margin-bottom: 1rem;
  }

  .upload-prompt p {
    margin: 0.25rem 0;
    color: #e2e2e8;
  }

  .upload-prompt .hint {
    color: #666;
    font-size: 0.85rem;
  }

  /* Preview */
  .preview-container {
    position: relative;
    display: inline-block;
    max-width: 100%;
  }

  .preview-image {
    max-width: 100%;
    max-height: 400px;
    border-radius: 8px;
    border: 1px solid #333;
  }

  .clear-btn {
    position: absolute;
    top: -10px;
    right: -10px;
    background: #ef4444;
    color: white;
    border: none;
    border-radius: 50%;
    width: 28px;
    height: 28px;
    cursor: pointer;
    font-size: 0.8rem;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  /* Actions */
  .actions {
    margin-bottom: 1.5rem;
  }

  .run-btn {
    background: #3b82f6;
    color: white;
    border: none;
    padding: 0.875rem 2rem;
    border-radius: 8px;
    font-size: 1rem;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.15s;
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
  }

  .run-btn:hover:not(:disabled) {
    background: #2563eb;
  }

  .run-btn:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .spinner {
    display: inline-block;
    width: 16px;
    height: 16px;
    border: 2px solid rgba(255,255,255,0.3);
    border-top-color: white;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }

  @keyframes spin {
    to { transform: rotate(360deg); }
  }

  /* Error Panel */
  .error-panel {
    background: rgba(239, 68, 68, 0.1);
    border: 1px solid rgba(239, 68, 68, 0.3);
    border-radius: 8px;
    padding: 1.25rem;
    margin-bottom: 1.5rem;
  }

  .error-panel h3 {
    margin: 0 0 0.5rem;
    color: #ef4444;
  }

  .error-panel p {
    margin: 0;
    color: #fca5a5;
  }

  /* Results */
  .results {
    margin-top: 2rem;
    padding-top: 2rem;
    border-top: 1px solid #222;
  }

  .results h3 {
    margin: 0 0 1.5rem;
    font-size: 1.2rem;
  }

  /* Insights */
  .insights-panel {
    background: #1a1a1c;
    border-radius: 8px;
    padding: 1.25rem;
    margin-bottom: 1.5rem;
  }

  .insights-panel h4 {
    margin: 0 0 1rem;
    font-size: 1rem;
    color: #aaa;
  }

  .insight {
    display: flex;
    gap: 0.75rem;
    padding: 0.875rem;
    background: #111113;
    border-radius: 6px;
    margin-bottom: 0.5rem;
    border-left: 3px solid;
  }

  .insight:last-child {
    margin-bottom: 0;
  }

  .insight-icon {
    font-weight: bold;
    font-size: 1.1rem;
    flex-shrink: 0;
  }

  .insight-content strong {
    display: block;
    margin-bottom: 0.25rem;
    font-size: 0.95rem;
  }

  .insight-content p {
    margin: 0;
    color: #888;
    font-size: 0.9rem;
    line-height: 1.5;
  }

  /* Visual Overlay */
  .overlay-section {
    margin-bottom: 2rem;
  }

  .overlay-section h4 {
    margin: 0 0 1rem;
    font-size: 1rem;
    color: #aaa;
  }

  .overlay-container {
    position: relative;
    display: inline-block;
    max-width: 100%;
    border-radius: 8px;
    overflow: hidden;
    border: 1px solid #333;
  }

  .overlay-base {
    max-width: 100%;
    max-height: 500px;
    display: block;
  }

  .region-overlay {
    position: absolute;
    border: 2px solid;
    background: rgba(255, 255, 255, 0.05);
    pointer-events: none;
    transition: background 0.2s;
  }

  .region-overlay:hover {
    background: rgba(255, 255, 255, 0.15);
  }

  .overlay-label {
    position: absolute;
    top: 0;
    left: 0;
    color: white;
    padding: 2px 8px;
    font-size: 0.75rem;
    font-weight: 600;
    border-bottom-right-radius: 4px;
    white-space: nowrap;
    pointer-events: none;
  }

  .overlay-hint {
    margin-top: 0.75rem;
    font-size: 0.85rem;
    color: #666;
  }

  /* Regions Grid */
  .regions-section {
    margin-bottom: 1.5rem;
  }

  .regions-section h4 {
    margin: 0 0 1rem;
    font-size: 1rem;
    color: #aaa;
  }

  .regions-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
    gap: 1rem;
  }

  .region-card {
    background: #1a1a1c;
    border: 1px solid #333;
    border-radius: 8px;
    padding: 1rem;
  }

  .region-header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.5rem;
  }

  .region-num {
    background: #3b82f6;
    color: white;
    width: 24px;
    height: 24px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.8rem;
    font-weight: 600;
  }

  .region-name {
    font-weight: 600;
    text-transform: capitalize;
  }

  .region-bbox {
    font-size: 0.8rem;
    color: #666;
    font-family: monospace;
    margin-bottom: 0.75rem;
  }

  .region-thumb {
    width: 100%;
    height: 120px;
    object-fit: cover;
    border-radius: 4px;
    border: 1px solid #333;
  }

  /* Raw Data */
  .raw-data {
    margin-top: 1rem;
    background: #1a1a1c;
    border-radius: 8px;
    padding: 1rem;
  }

  .raw-data summary {
    cursor: pointer;
    color: #888;
    font-size: 0.9rem;
    user-select: none;
  }

  .raw-data summary:hover {
    color: #e2e2e8;
  }

  .raw-data pre {
    margin-top: 1rem;
    padding: 1rem;
    background: #0a0a0b;
    border-radius: 6px;
    overflow-x: auto;
    font-size: 0.8rem;
    color: #888;
    max-height: 400px;
    overflow-y: auto;
  }

  .command-output {
    white-space: pre-wrap;
    word-break: break-all;
  }

  /* Placeholder */
  .placeholder {
    text-align: center;
    padding: 4rem 2rem;
    color: #666;
  }

  .placeholder .hint {
    font-size: 0.9rem;
    color: #555;
    margin-top: 1rem;
  }
</style>
