<script>
  import { onMount, onDestroy } from 'svelte';

  export let data;

  const { id } = data;
  let meta = data.meta;
  let htmlCode = data.htmlCode;

  let activeTab = 'preview';
  let polling = false;
  let metaInterval = null;
  let logInterval = null;

  // Activity feed
  let logEvents = [];
  let logSince = 0;
  let logEl = null;
  let userScrolled = false;

  // ── Inspect mode ─────────────────────────────────────────────────────────────
  let iframeEl = null;
  let iframeReady = false;
  let inspectEnabled = false;
  let selectedElements = [];
  let _inspHoverFn = null;
  let _inspClickFn = null;
  let _inspStyle = null;

  // ── Crop tool ─────────────────────────────────────────────────────────────────
  let cropActive = null;   // null | 'reference' | 'snapshot'
  let refImgEl = null;
  let snapImgEl = null;
  let cropDragging = false;
  let cropStart = null;
  let cropRect = null;     // {x, y, w, h} in overlay-div coords
  let selectedCrops = [];

  // ── Feedback drawer ───────────────────────────────────────────────────────────
  let feedbackOpen = false;
  let feedbackText = '';
  let feedbackSaving = false;
  let feedbackSavedFolder = null;

  const TERMINAL = new Set(['done', 'stuck']);

  // ── helpers ──────────────────────────────────────────────────────────────────

  function statusColor(s) {
    return s === 'done' ? '#22c55e' : s === 'stuck' ? '#ef4444'
         : s === 'iterating' ? '#f59e0b' : '#6b7280';
  }

  function fmtTime(ts) {
    if (!ts) return '';
    return new Date(ts).toLocaleTimeString('en', {
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
    });
  }

  // ── meta polling ─────────────────────────────────────────────────────────────

  async function pollMeta() {
    try {
      const res = await fetch(`/api/components/${id}`);
      if (!res.ok) return;
      const d = await res.json();
      const { html_code, ...m } = d;
      meta = m;
      if (html_code) htmlCode = html_code;
      if (TERMINAL.has(meta.status)) stopPolling();
    } catch (_) {}
  }

  // ── log / activity polling ───────────────────────────────────────────────────

  async function pollLog() {
    try {
      const res = await fetch(`/api/components/${id}/log?since=${logSince}`);
      if (!res.ok) return;
      const d = await res.json();
      if (d.events.length > 0) {
        logEvents = [...logEvents, ...d.events];
        logSince = d.next;
        setTimeout(() => {
          if (!userScrolled && logEl) logEl.scrollTop = logEl.scrollHeight;
        }, 30);
      } else {
        if (d.next > logSince) logSince = d.next;
      }
    } catch (_) {}
  }

  function onLogScroll() {
    if (!logEl) return;
    userScrolled = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight > 60;
  }

  // ── lifecycle ─────────────────────────────────────────────────────────────────

  function startPolling() {
    if (metaInterval) return;
    polling = true;
    metaInterval = setInterval(pollMeta, 3000);
    logInterval = setInterval(pollLog, 500);
  }

  function stopPolling() {
    polling = false;
    if (metaInterval) { clearInterval(metaInterval); metaInterval = null; }
    if (logInterval) { clearInterval(logInterval); logInterval = null; }
  }

  onMount(() => {
    pollLog();
    if (!TERMINAL.has(meta.status)) startPolling();
  });

  onDestroy(() => {
    stopPolling();
    _removeInspect();
  });

  // ── iframe inspect ────────────────────────────────────────────────────────────

  function onIframeLoad() {
    iframeReady = true;
    if (inspectEnabled) _applyInspect();
  }

  function toggleInspect() {
    inspectEnabled = !inspectEnabled;
    if (!iframeReady) return;
    if (inspectEnabled) _applyInspect();
    else _removeInspect();
  }

  function _applyInspect() {
    const doc = iframeEl?.contentDocument;
    if (!doc) return;

    const s = doc.createElement('style');
    s.id = '__cl_inspect_style';
    s.textContent = `
      .__cl_hover   { outline: 2px solid rgba(59,130,246,0.85) !important; outline-offset: 1px !important; cursor: crosshair !important; }
      .__cl_sel     { outline: 2px solid rgba(34,197,94,0.9)   !important; outline-offset: 1px !important; background: rgba(34,197,94,0.06) !important; }
    `;
    doc.head.appendChild(s);
    _inspStyle = s;

    _inspHoverFn = (e) => {
      doc.querySelectorAll('.__cl_hover').forEach(el => el.classList.remove('__cl_hover'));
      if (e.target !== doc.body && e.target !== doc.documentElement)
        e.target.classList.add('__cl_hover');
    };

    _inspClickFn = (e) => {
      e.preventDefault();
      e.stopPropagation();
      const el = e.target;
      if (el === doc.body || el === doc.documentElement) return;

      const rect = el.getBoundingClientRect();
      const cs = doc.defaultView?.getComputedStyle(el);
      const info = {
        tagName: el.tagName.toLowerCase(),
        id: el.id || null,
        classes: [...el.classList].filter(c => !c.startsWith('__cl')),
        text: el.innerText?.trim().slice(0, 200) || null,
        rect: { x: Math.round(rect.x), y: Math.round(rect.y), w: Math.round(rect.width), h: Math.round(rect.height) },
        styles: cs ? {
          display: cs.display, position: cs.position,
          color: cs.color, backgroundColor: cs.backgroundColor,
          fontSize: cs.fontSize, fontWeight: cs.fontWeight,
          padding: cs.padding, margin: cs.margin,
          width: cs.width, height: cs.height,
          borderRadius: cs.borderRadius, flexDirection: cs.flexDirection, gap: cs.gap,
        } : {},
      };

      if (el.classList.contains('__cl_sel')) {
        el.classList.remove('__cl_sel');
        // Remove from list by matching tag+rect
        selectedElements = selectedElements.filter(s =>
          !(s.tagName === info.tagName && s.rect.x === info.rect.x && s.rect.y === info.rect.y)
        );
      } else {
        el.classList.add('__cl_sel');
        selectedElements = [...selectedElements, info];
        feedbackOpen = true;
      }
    };

    doc.addEventListener('mouseover', _inspHoverFn);
    doc.addEventListener('click', _inspClickFn, true);
  }

  function _removeInspect() {
    const doc = iframeEl?.contentDocument;
    if (!doc) return;
    _inspStyle?.remove(); _inspStyle = null;
    if (_inspHoverFn) { doc.removeEventListener('mouseover', _inspHoverFn); _inspHoverFn = null; }
    if (_inspClickFn) { doc.removeEventListener('click', _inspClickFn, true); _inspClickFn = null; }
    doc.querySelectorAll('.__cl_hover, .__cl_sel').forEach(el =>
      el.classList.remove('__cl_hover', '__cl_sel')
    );
  }

  function clearElements() {
    selectedElements = [];
    const doc = iframeEl?.contentDocument;
    if (doc) doc.querySelectorAll('.__cl_sel').forEach(el => el.classList.remove('__cl_sel'));
  }

  // ── crop tool ─────────────────────────────────────────────────────────────────

  function activateCrop(source) {
    cropActive = source;
    cropRect = null;
    cropDragging = false;
    // Switch to the right tab
    if (source === 'reference') activeTab = 'reference';
    if (source === 'snapshot') activeTab = 'snapshot';
  }

  function cancelCrop() {
    cropActive = null;
    cropRect = null;
    cropDragging = false;
  }

  function onCropDown(e) {
    e.preventDefault();
    const rect = e.currentTarget.getBoundingClientRect();
    cropDragging = true;
    cropStart = { x: e.clientX - rect.left, y: e.clientY - rect.top };
    cropRect = null;
  }

  function onCropMove(e) {
    if (!cropDragging || !cropStart) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const x = Math.max(0, Math.min(e.clientX - rect.left, rect.width));
    const y = Math.max(0, Math.min(e.clientY - rect.top, rect.height));
    cropRect = {
      x: Math.min(cropStart.x, x),
      y: Math.min(cropStart.y, y),
      w: Math.abs(x - cropStart.x),
      h: Math.abs(y - cropStart.y),
    };
  }

  function onCropUp() {
    cropDragging = false;
  }

  async function confirmCrop() {
    if (!cropRect || cropRect.w < 8 || cropRect.h < 8) return;
    const img = cropActive === 'reference' ? refImgEl : snapImgEl;
    if (!img) return;

    // The overlay covers the container; get the actual image display rect
    const overlayEl = img.parentElement;
    const overlayRect = overlayEl.getBoundingClientRect();
    const imgRect = img.getBoundingClientRect();

    // Offset of image within the overlay container
    const offX = imgRect.left - overlayRect.left;
    const offY = imgRect.top - overlayRect.top;

    // Translate crop rect from overlay space to image-display space
    const relX = cropRect.x - offX;
    const relY = cropRect.y - offY;

    const scaleX = img.naturalWidth / imgRect.width;
    const scaleY = img.naturalHeight / imgRect.height;

    const sx = Math.max(0, Math.round(relX * scaleX));
    const sy = Math.max(0, Math.round(relY * scaleY));
    const sw = Math.min(img.naturalWidth - sx, Math.max(1, Math.round(cropRect.w * scaleX)));
    const sh = Math.min(img.naturalHeight - sy, Math.max(1, Math.round(cropRect.h * scaleY)));

    if (sw <= 0 || sh <= 0) return;

    const canvas = document.createElement('canvas');
    canvas.width = sw; canvas.height = sh;
    canvas.getContext('2d').drawImage(img, sx, sy, sw, sh, 0, 0, sw, sh);
    const dataUrl = canvas.toDataURL('image/png');

    selectedCrops = [...selectedCrops, { label: cropActive, dataUrl, rect: { x: sx, y: sy, w: sw, h: sh } }];
    cropRect = null;
    cropActive = null;
    feedbackOpen = true;
  }

  function removeCrop(i) {
    selectedCrops = selectedCrops.filter((_, idx) => idx !== i);
  }

  // ── latest screenshot for snapshot tab ───────────────────────────────────────

  $: latestSnapNum = meta.iterations.length > 0
    ? (meta.iterations[meta.iterations.length - 1].num ?? meta.iterations.length)
    : null;
  $: latestSnapSrc = latestSnapNum
    ? `/components/${id}/screenshots/${latestSnapNum}.png`
    : null;

  // ── save feedback ─────────────────────────────────────────────────────────────

  async function saveFeedback() {
    if (!feedbackText.trim() && selectedElements.length === 0 && selectedCrops.length === 0) return;
    feedbackSaving = true;
    feedbackSavedFolder = null;
    try {
      const res = await fetch(`/api/components/${id}/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: feedbackText,
          elements: selectedElements,
          crops: selectedCrops.map(c => ({ label: c.label, dataUrl: c.dataUrl, rect: c.rect })),
        }),
      });
      const d = await res.json();
      if (d.ok) {
        feedbackSavedFolder = d.folder;
        // Reset selections
        feedbackText = '';
        selectedElements = [];
        selectedCrops = [];
        clearElements();
      }
    } catch (_) {}
    feedbackSaving = false;
  }
</script>

<svelte:head>
  <title>{meta.name} - UI Cloner</title>
</svelte:head>

<div class="root" class:drawer-open={feedbackOpen}>
  <header>
    <a href="/" class="back">← Back</a>
    <div class="header-main">
      <h1>{meta.name}</h1>
      <span class="status-badge"
            style="background:{statusColor(meta.status)}18;color:{statusColor(meta.status)};border-color:{statusColor(meta.status)}40">
        {meta.status}
      </span>
      {#if polling}
        <span class="live-badge">LIVE</span>
        <button class="stop-btn" onclick={stopPolling}>Stop</button>
      {/if}
      <button class="feedback-btn" class:active={feedbackOpen}
              onclick={() => { feedbackOpen = !feedbackOpen; feedbackSavedFolder = null; }}>
        {feedbackOpen ? '✕ Feedback' : '+ Feedback'}
        {#if selectedElements.length + selectedCrops.length > 0}
          <span class="fb-count">{selectedElements.length + selectedCrops.length}</span>
        {/if}
      </button>
    </div>
    <div class="meta-row">
      <span>{meta.iterations.length} iterations</span>
    </div>
  </header>

  <div class="main-grid">

    <!-- ── Left: preview ──────────────────────────────────────────────────── -->
    <div class="panel preview-panel">
      <div class="tabs">
        <button class:active={activeTab === 'preview'} onclick={() => activeTab = 'preview'}>Preview</button>
        <button class:active={activeTab === 'code'}    onclick={() => activeTab = 'code'}>Code</button>
        <button class:active={activeTab === 'reference'} onclick={() => activeTab = 'reference'}>Reference</button>
        <button class:active={activeTab === 'snapshot'}  onclick={() => activeTab = 'snapshot'}>Snapshot</button>

        {#if activeTab === 'preview'}
          <button class="tool-btn" class:tool-active={inspectEnabled} onclick={toggleInspect}
                  title="Click elements in the preview to select them for feedback">
            Inspect{#if selectedElements.length > 0} ({selectedElements.length}){/if}
          </button>
        {/if}
        {#if activeTab === 'reference' && meta.reference}
          <button class="tool-btn" class:tool-active={cropActive === 'reference'}
                  onclick={() => cropActive === 'reference' ? cancelCrop() : activateCrop('reference')}
                  title="Drag to select a region of the reference image">
            {cropActive === 'reference' ? 'Cancel' : 'Crop'}
          </button>
        {/if}
        {#if activeTab === 'snapshot' && latestSnapSrc}
          <button class="tool-btn" class:tool-active={cropActive === 'snapshot'}
                  onclick={() => cropActive === 'snapshot' ? cancelCrop() : activateCrop('snapshot')}
                  title="Drag to select a region of the latest screenshot">
            {cropActive === 'snapshot' ? 'Cancel' : 'Crop'}
          </button>
        {/if}
      </div>

      <!-- Preview tab -->
      {#if activeTab === 'preview'}
        <div class="preview-frame">
          <iframe bind:this={iframeEl}
            src="/components/{id}/preview.html?v={meta.iterations.length}"
            title="Preview"
            onload={onIframeLoad}
          ></iframe>
          {#if inspectEnabled}
            <div class="inspect-overlay-hint">Inspect ON — click elements to select</div>
          {/if}
        </div>

      <!-- Code tab -->
      {:else if activeTab === 'code'}
        <div class="code-view">
          <pre><code>{htmlCode}</code></pre>
        </div>

      <!-- Reference tab -->
      {:else if activeTab === 'reference'}
        <div class="img-tab-view">
          {#if meta.reference}
            <div class="crop-wrap">
              <img bind:this={refImgEl}
                src="/components/{id}/{meta.reference}"
                alt="Reference"
                class:crop-img-mode={cropActive === 'reference'}>
              {#if cropActive === 'reference'}
                <div class="crop-overlay"
                  role="none"
                  onmousedown={onCropDown}
                  onmousemove={onCropMove}
                  onmouseup={onCropUp}
                  onmouseleave={onCropUp}
                >
                  {#if cropRect}
                    <div class="crop-sel" style="left:{cropRect.x}px;top:{cropRect.y}px;width:{cropRect.w}px;height:{cropRect.h}px"></div>
                  {/if}
                </div>
              {/if}
            </div>
            {#if cropActive === 'reference'}
              <div class="crop-controls">
                {#if cropRect && cropRect.w > 8}
                  <button class="crop-confirm" onclick={confirmCrop}>✓ Capture region</button>
                {:else}
                  <span class="crop-hint">Drag to select a region</span>
                {/if}
                <button class="crop-cancel" onclick={cancelCrop}>Cancel</button>
              </div>
            {/if}
          {:else}
            <p class="empty-hint">No reference image</p>
          {/if}
        </div>

      <!-- Snapshot tab -->
      {:else if activeTab === 'snapshot'}
        <div class="img-tab-view">
          {#if latestSnapSrc}
            <div class="crop-wrap">
              <img bind:this={snapImgEl}
                src="{latestSnapSrc}?t={meta.iterations.length}"
                alt="Latest snapshot"
                class:crop-img-mode={cropActive === 'snapshot'}
                onerror={e => e.currentTarget.closest('.img-tab-view').innerHTML = '<p class="empty-hint">No snapshot yet</p>'}>
              {#if cropActive === 'snapshot'}
                <div class="crop-overlay"
                  role="none"
                  onmousedown={onCropDown}
                  onmousemove={onCropMove}
                  onmouseup={onCropUp}
                  onmouseleave={onCropUp}
                >
                  {#if cropRect}
                    <div class="crop-sel" style="left:{cropRect.x}px;top:{cropRect.y}px;width:{cropRect.w}px;height:{cropRect.h}px"></div>
                  {/if}
                </div>
              {/if}
            </div>
            {#if cropActive === 'snapshot'}
              <div class="crop-controls">
                {#if cropRect && cropRect.w > 8}
                  <button class="crop-confirm" onclick={confirmCrop}>✓ Capture region</button>
                {:else}
                  <span class="crop-hint">Drag to select a region</span>
                {/if}
                <button class="crop-cancel" onclick={cancelCrop}>Cancel</button>
              </div>
            {/if}
          {:else}
            <p class="empty-hint">No snapshot yet. Run an iteration first.</p>
          {/if}
        </div>
      {/if}
    </div>

    <!-- ── Middle: iteration history ─────────────────────────────────────── -->
    <div class="panel history-panel">
      <div class="panel-header"><h2>Iterations</h2></div>
      {#if meta.iterations.length === 0}
        <p class="empty-hint">No iterations yet.</p>
      {:else}
        <div class="scroll-body">
          {#each [...meta.iterations].reverse() as iter}
            <div class="iter-card">
              <div class="iter-head">
                <span class="iter-num">#{iter.num}</span>
                <span class="iter-time">{fmtTime(iter.created_at)}</span>
              </div>
              {#if iter.has_screenshot}
                <div class="iter-shots">
                  <img src="/components/{id}/screenshots/{iter.num}.png" alt="Screenshot {iter.num}">
                  {#if iter.has_diff}
                    <img src="/components/{id}/diffs/{iter.num}.png" alt="Diff {iter.num}" class="diff-img">
                  {/if}
                </div>
              {:else}
                <div class="iter-shots">
                  <img src="/components/{id}/screenshots/{iter.num}.png" alt="Screenshot {iter.num}"
                       onerror={e => e.currentTarget.style.display='none'}>
                </div>
              {/if}
              {#if iter.console_errors?.length > 0}
                <div class="iter-errors">
                  {#each iter.console_errors as err}
                    <code>{err.text || err}</code>
                  {/each}
                </div>
              {/if}
              {#if iter.note}
                <div class="iter-note">{iter.note}</div>
              {/if}
            </div>
          {/each}
        </div>
      {/if}
    </div>

    <!-- ── Right: live activity feed ─────────────────────────────────────── -->
    <div class="panel activity-panel">
      <div class="panel-header">
        <h2>Activity</h2>
        {#if logEvents.length > 0}
          <button class="clear-btn" onclick={() => logEvents = []}>clear</button>
        {/if}
      </div>

      {#if logEvents.length === 0}
        <p class="empty-hint">No activity yet. Start a loop to see live output here.</p>
      {:else}
        <div class="log-feed" bind:this={logEl} onscroll={onLogScroll}>
          {#each logEvents as ev}

            {#if ev.type === 'html_written'}
              <div class="ev ev-html">
                <span class="ev-ts">{fmtTime(ev.ts)}</span>
                <div class="ev-body">
                  <span class="ev-tag tag-write">HTML</span>
                  <span class="ev-muted">preview.html updated</span>
                </div>
              </div>

            {:else if ev.type === 'screenshot'}
              <div class="ev ev-screenshot">
                <span class="ev-ts">{fmtTime(ev.ts)}</span>
                <div class="ev-body">
                  <span class="ev-tag tag-img">screenshot #{ev.num}</span>
                  <img class="ev-img" src="{ev.path}?t={ev.mtime}" alt="screenshot {ev.num}">
                </div>
              </div>

            {:else if ev.type === 'diff'}
              <div class="ev ev-diff">
                <span class="ev-ts">{fmtTime(ev.ts)}</span>
                <div class="ev-body">
                  <span class="ev-tag tag-diff">diff #{ev.num}</span>
                  <img class="ev-img ev-diff-img" src="{ev.path}?t={ev.mtime}" alt="diff {ev.num}">
                </div>
              </div>

            {:else if ev.type === 'current_render'}
              <div class="ev ev-current">
                <span class="ev-ts">{fmtTime(ev.ts)}</span>
                <div class="ev-body">
                  <span class="ev-tag tag-live">render</span>
                  <img class="ev-img" src="{ev.path}?t={ev.mtime}" alt="current render">
                </div>
              </div>

            {:else if ev.type === 'meta_update'}
              <div class="ev ev-meta">
                <span class="ev-ts">{fmtTime(ev.ts)}</span>
                <div class="ev-body">
                  <span class="ev-tag tag-info">iter {ev.iteration_count}</span>
                  {#if ev.latest_iter?.note}
                    <span class="ev-prose">{ev.latest_iter.note}</span>
                  {/if}
                  <span class="ev-status" style="color:{statusColor(ev.status)}">{ev.status}</span>
                </div>
              </div>

            {:else if ev.type === 'loop_start'}
              <div class="ev ev-loop-start">
                <span class="ev-ts">{fmtTime(ev.ts)}</span>
                <div class="ev-body">
                  <span class="ev-tag tag-info">start</span>
                  <span class="ev-text">Loop started · {ev.model} · max {ev.max_iter} iters</span>
                  {#if ev.ref_thumb}
                    <img class="ev-img" src="data:image/jpeg;base64,{ev.ref_thumb}" alt="reference">
                  {/if}
                  {#if ev.colors?.length > 0}
                    <div class="ev-swatches">
                      {#each ev.colors as c}
                        <div class="ev-swatch-wrap" title="{c.hex} · {c.coverage_pct}%">
                          <div class="ev-swatch" style="background:{c.hex}"></div>
                          <span class="ev-swatch-hex">{c.hex}</span>
                          <span class="ev-swatch-pct">{c.coverage_pct}%</span>
                        </div>
                      {/each}
                    </div>
                  {/if}
                </div>
              </div>

            {:else if ev.type === 'iteration_start'}
              <div class="ev ev-iter-sep">
                <span class="ev-sep-line">── Iteration {ev.iter} / {ev.total} ──</span>
              </div>

            {:else if ev.type === 'images_to_model'}
              <div class="ev ev-images">
                <span class="ev-ts">{fmtTime(ev.ts)}</span>
                <div class="ev-body">
                  <span class="ev-tag tag-img">→ model</span>
                  <div class="ev-thumbrow">
                    {#each (ev.thumbs || []) as thumb, i}
                      <div class="ev-thumb-wrap">
                        <img class="ev-img" src="data:image/jpeg;base64,{thumb}" alt={ev.labels?.[i] ?? ''}>
                        <span class="ev-thumb-label">{ev.labels?.[i] ?? ''}</span>
                      </div>
                    {/each}
                  </div>
                </div>
              </div>

            {:else if ev.type === 'model_thinking'}
              <div class="ev ev-thinking">
                <span class="ev-ts">{fmtTime(ev.ts)}</span>
                <div class="ev-body">
                  <span class="ev-tag tag-model">model</span>
                  <span class="ev-muted">thinking…</span>
                </div>
              </div>

            {:else if ev.type === 'tool_call'}
              <div class="ev ev-tool-call">
                <span class="ev-ts">{fmtTime(ev.ts)}</span>
                <div class="ev-body">
                  <span class="ev-arrow">→</span>
                  <span class="ev-tool-name">{ev.tool}</span>
                  {#if ev.args_preview}
                    <span class="ev-args">{ev.args_preview}</span>
                  {/if}
                </div>
              </div>

            {:else if ev.type === 'tool_result'}
              <div class="ev ev-tool-result">
                <span class="ev-ts">{fmtTime(ev.ts)}</span>
                <div class="ev-body">
                  <span class="ev-arrow ok">←</span>
                  <span class="ev-tool-name">{ev.tool}</span>
                  {#if ev.error}
                    <span class="ev-error">{ev.error}</span>
                  {:else}
                    {#if ev.pixel_diff_pct != null}
                      <span class="ev-muted">{ev.pixel_diff_pct}% pixels differ</span>
                    {/if}
                    {#if ev.console_error_count}
                      <span class="ev-cerr">{ev.console_error_count} console error{ev.console_error_count > 1 ? 's' : ''}</span>
                    {/if}
                    {#if ev.page_height}<span class="ev-muted">{ev.page_height}px</span>{/if}
                    {#if ev.node_count}<span class="ev-muted">{ev.node_count} nodes</span>{/if}
                    {#if ev.screenshot_thumb}
                      <img class="ev-img" src="data:image/jpeg;base64,{ev.screenshot_thumb}" alt="screenshot">
                    {/if}
                    {#if ev.overlay_thumb}
                      <img class="ev-img ev-diff-img" src="data:image/jpeg;base64,{ev.overlay_thumb}" alt="diff">
                    {/if}
                    {#if ev.console_errors?.length > 0}
                      <div class="ev-console-errors">
                        {#each ev.console_errors as err}
                          <code>{err.text || err}</code>
                        {/each}
                      </div>
                    {/if}
                    {#if ev.html_preview}
                      <details class="ev-details">
                        <summary>HTML preview</summary>
                        <pre>{ev.html_preview}</pre>
                      </details>
                    {/if}
                  {/if}
                </div>
              </div>

            {:else if ev.type === 'model_text'}
              <div class="ev ev-model-text">
                <span class="ev-ts">{fmtTime(ev.ts)}</span>
                <div class="ev-body">
                  <span class="ev-tag tag-model">model</span>
                  <div class="ev-prose">{ev.text}</div>
                </div>
              </div>

            {:else if ev.type === 'colors_extracted'}
              <div class="ev ev-colors">
                <span class="ev-ts">{fmtTime(ev.ts)}</span>
                <div class="ev-body">
                  <span class="ev-tag tag-info">colors</span>
                  {#if ev.colors?.length > 0}
                    <div class="ev-swatches">
                      {#each ev.colors as c}
                        <div class="ev-swatch-wrap" title="{c.hex} · {c.coverage_pct}%">
                          <div class="ev-swatch" style="background:{c.hex}"></div>
                          <span class="ev-swatch-hex">{c.hex}</span>
                          <span class="ev-swatch-pct">{c.coverage_pct}%</span>
                        </div>
                      {/each}
                    </div>
                  {/if}
                </div>
              </div>

            {:else if ev.type === 'scratchpad_update'}
              <div class="ev ev-scratchpad">
                <span class="ev-ts">{fmtTime(ev.ts)}</span>
                <div class="ev-body">
                  <span class="ev-tag tag-pad">scratchpad</span>
                  <div class="ev-prose">{ev.excerpt}</div>
                </div>
              </div>

            {:else if ev.type === 'gemini_feedback'}
              <div class="ev ev-gemini">
                <span class="ev-ts">{fmtTime(ev.ts)}</span>
                <div class="ev-body">
                  <span class="ev-tag tag-gemini">gemini</span>
                  {#if ev.context}<span class="ev-muted">{ev.context}{ev.prompt ? ' — ' + ev.prompt : ''}</span>{/if}
                  <details class="ev-gemini-details" open>
                    <summary>{(ev.text || '').slice(0, 140)}{(ev.text?.length ?? 0) > 140 ? '…' : ''}</summary>
                    <div class="ev-prose ev-gemini-full">{ev.text}</div>
                  </details>
                </div>
              </div>

            {:else if ev.type === 'iteration_end'}
              <div class="ev ev-iter-end">
                <span class="ev-ts">{fmtTime(ev.ts)}</span>
                <div class="ev-body">
                  <span class="ev-text">Iter {ev.iter} done</span>
                </div>
              </div>

            {:else if ev.type === 'status'}
              <div class="ev ev-status-msg">
                <span class="ev-ts">{fmtTime(ev.ts)}</span>
                <div class="ev-body">
                  <span class="ev-muted">{ev.msg}</span>
                </div>
              </div>

            {:else if ev.type === 'converged' || ev.type === 'loop_end'}
              <div class="ev ev-loop-end">
                <span class="ev-ts">{fmtTime(ev.ts)}</span>
                <div class="ev-body">
                  <span class="ev-tag tag-ok">{ev.type === 'converged' ? 'converged' : 'done'}</span>
                  {#if ev.total_iter != null}
                    <span class="ev-muted">{ev.total_iter} iterations</span>
                  {/if}
                </div>
              </div>

            {/if}

          {/each}
        </div>
      {/if}
    </div>

  </div>

  <!-- ── Feedback drawer ─────────────────────────────────────────────────── -->
  {#if feedbackOpen}
    <div class="feedback-drawer">
      <div class="fb-header">
        <span class="fb-title">Feedback Builder</span>
        <span class="fb-hint">Select elements in Preview or crop regions in Reference / Snapshot, then describe the issue.</span>
        <button class="fb-close" onclick={() => feedbackOpen = false}>✕</button>
      </div>

      <div class="fb-body">

        <!-- Selections column -->
        <div class="fb-selections">
          {#if selectedElements.length > 0}
            <div class="fb-section-label">
              Selected elements
              <button class="fb-clear-link" onclick={clearElements}>clear all</button>
            </div>
            {#each selectedElements as el, i}
              <div class="fb-el">
                <span class="fb-el-tag">&lt;{el.tagName}&gt;</span>
                {#if el.id}<span class="fb-el-attr">#{el.id}</span>{/if}
                {#if el.classes.length > 0}<span class="fb-el-attr">.{el.classes.join('.')}</span>{/if}
                {#if el.text}<span class="fb-el-text">"{el.text.slice(0,60)}"</span>{/if}
                <span class="fb-el-rect">{el.rect.w}×{el.rect.h}</span>
                <button class="fb-remove" onclick={() => { selectedElements = selectedElements.filter((_,j)=>j!==i); }}>×</button>
              </div>
            {/each}
          {/if}

          {#if selectedCrops.length > 0}
            <div class="fb-section-label" style="margin-top:{selectedElements.length ? '0.75rem' : 0}">
              Cropped regions
            </div>
            <div class="fb-crops-row">
              {#each selectedCrops as crop, i}
                <div class="fb-crop-thumb">
                  <img src={crop.dataUrl} alt="crop {i}">
                  <span class="fb-crop-label">{crop.label}</span>
                  <button class="fb-crop-remove" onclick={() => removeCrop(i)}>×</button>
                </div>
              {/each}
            </div>
          {/if}

          {#if selectedElements.length === 0 && selectedCrops.length === 0}
            <p class="fb-empty">
              Switch to <strong>Preview</strong> and click <strong>Inspect</strong> to select elements,<br>
              or go to <strong>Reference / Snapshot</strong> and click <strong>Crop</strong> to select regions.
            </p>
          {/if}
        </div>

        <!-- Query column -->
        <div class="fb-query-col">
          <textarea
            bind:value={feedbackText}
            placeholder="Describe what needs to change…&#10;e.g. This button should be outside the card div but still anchored to its bottom."
            class="fb-textarea"
          ></textarea>

          <div class="fb-actions">
            {#if feedbackSavedFolder}
              <div class="fb-saved">
                ✓ Saved to <code>feedback/{feedbackSavedFolder}/</code>
                — point your agent at that folder.
              </div>
            {/if}
            <button class="fb-save-btn"
              disabled={feedbackSaving || (!feedbackText.trim() && selectedElements.length === 0 && selectedCrops.length === 0)}
              onclick={saveFeedback}>
              {feedbackSaving ? 'Saving…' : 'Save Feedback'}
            </button>
          </div>
        </div>

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
    min-height: 100vh;
    padding: 1rem 1.25rem 1.5rem;
    display: flex;
    flex-direction: column;
  }
  .root.drawer-open { padding-bottom: calc(1.5rem + 280px); }

  /* ── Header ── */
  header { margin-bottom: 1rem; }

  .back { color: #555; text-decoration: none; font-size: 0.82rem; }
  .back:hover { color: #999; }

  .header-main {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin: 0.4rem 0 0.3rem;
    flex-wrap: wrap;
  }

  h1 { margin: 0; font-size: 1.35rem; font-weight: 600; letter-spacing: -0.02em; }

  .status-badge {
    font-size: 0.65rem; font-weight: 700; letter-spacing: 0.07em;
    text-transform: uppercase; padding: 0.2rem 0.6rem;
    border-radius: 999px; border: 1px solid transparent;
  }

  .live-badge {
    font-size: 0.62rem; font-weight: 700; letter-spacing: 0.08em;
    color: #22c55e; background: #22c55e18; border: 1px solid #22c55e40;
    padding: 0.2rem 0.5rem; border-radius: 999px;
    animation: pulse 2s ease-in-out infinite;
  }

  @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.45; } }

  .stop-btn {
    font-size: 0.68rem; color: #ef4444; background: #2a1515;
    border: 1px solid #3a1515; border-radius: 5px;
    padding: 0.15rem 0.5rem; cursor: pointer;
  }
  .stop-btn:hover { background: #3a1515; }

  .feedback-btn {
    margin-left: auto; font-size: 0.75rem; font-weight: 600;
    color: #a78bfa; background: #1a1a2a; border: 1px solid #2a2a40;
    border-radius: 6px; padding: 0.25rem 0.65rem; cursor: pointer;
    display: flex; align-items: center; gap: 0.4rem;
  }
  .feedback-btn.active { background: #2a2040; border-color: #a78bfa40; }
  .feedback-btn:hover { background: #222232; }

  .fb-count {
    background: #a78bfa; color: #0a0a0b; border-radius: 999px;
    font-size: 0.58rem; font-weight: 700; padding: 0.05rem 0.35rem; min-width: 1rem; text-align: center;
  }

  .meta-row { display: flex; gap: 1.25rem; font-size: 0.82rem; color: #555; }

  /* ── Grid ── */
  .main-grid {
    display: grid;
    grid-template-columns: 1fr 260px 300px;
    gap: 1rem;
    flex: 1;
    height: calc(100vh - 120px);
  }

  /* ── Panels ── */
  .panel {
    background: #111113; border: 1px solid #1e1e20; border-radius: 10px;
    display: flex; flex-direction: column; overflow: hidden; min-height: 0;
  }

  .panel-header {
    display: flex; justify-content: space-between; align-items: center;
    padding: 0.55rem 0.85rem; border-bottom: 1px solid #1e1e20; flex-shrink: 0;
  }

  .panel-header h2 {
    margin: 0; font-size: 0.75rem; font-weight: 600; color: #555;
    text-transform: uppercase; letter-spacing: 0.07em;
  }

  .clear-btn { font-size: 0.7rem; color: #3a3a40; background: none; border: none; cursor: pointer; padding: 0.1rem 0.3rem; }
  .clear-btn:hover { color: #777; }

  .scroll-body { flex: 1; overflow-y: auto; padding: 0.5rem; display: flex; flex-direction: column; gap: 0.5rem; }

  .empty-hint { padding: 2rem 1rem; text-align: center; font-size: 0.8rem; color: #3a3a40; margin: 0; }

  /* ── Preview panel ── */
  .tabs {
    display: flex; border-bottom: 1px solid #1e1e20; flex-shrink: 0; align-items: center; flex-wrap: wrap;
  }

  .tabs button {
    background: none; border: none; padding: 0.5rem 0.6rem;
    font-size: 0.75rem; color: #444; cursor: pointer;
  }
  .tabs button.active { color: #e2e2e8; background: #191919; }
  .tabs button:hover:not(.active) { color: #888; }

  .tool-btn {
    margin-left: auto; font-size: 0.68rem; font-weight: 600;
    color: #6b7280; background: none; border: 1px solid #2a2a2e;
    border-radius: 4px; padding: 0.2rem 0.5rem; cursor: pointer; margin-right: 0.4rem;
  }
  .tool-btn.tool-active { color: #a78bfa; border-color: #a78bfa50; background: #1a1a2a; }
  .tool-btn:hover { color: #ccc; }

  .preview-frame { flex: 1; background: #fff; position: relative; }
  .preview-frame iframe { width: 100%; height: 100%; border: none; }

  .inspect-overlay-hint {
    position: absolute; bottom: 0.5rem; left: 50%; transform: translateX(-50%);
    background: rgba(59,130,246,0.9); color: #fff; font-size: 0.68rem; font-weight: 600;
    padding: 0.2rem 0.6rem; border-radius: 4px; pointer-events: none; white-space: nowrap;
  }

  .code-view { flex: 1; overflow: auto; background: #0d0d0e; }
  .code-view pre { margin: 0; padding: 1rem; font-family: monospace; font-size: 0.76rem; color: #ccc; white-space: pre-wrap; }

  /* ── Image tabs (reference / snapshot) ── */
  .img-tab-view { flex: 1; display: flex; flex-direction: column; overflow: hidden; }

  .crop-wrap { position: relative; flex: 1; overflow: auto; background: #1a1a1c; }
  .crop-wrap img { display: block; width: 100%; height: auto; }
  .crop-wrap img.crop-img-mode { cursor: default; }

  .crop-overlay {
    position: absolute; inset: 0; cursor: crosshair; z-index: 2;
  }
  .crop-sel {
    position: absolute; border: 2px dashed #3b82f6;
    background: rgba(59,130,246,0.1); pointer-events: none;
  }

  .crop-controls {
    display: flex; align-items: center; gap: 0.5rem; padding: 0.4rem 0.6rem;
    background: #0d0d0e; border-top: 1px solid #1e1e20; flex-shrink: 0;
  }
  .crop-hint { font-size: 0.72rem; color: #3a3a44; }
  .crop-confirm {
    font-size: 0.72rem; font-weight: 600; color: #22c55e;
    background: #0e2a1a; border: 1px solid #22c55e40; border-radius: 4px;
    padding: 0.2rem 0.5rem; cursor: pointer;
  }
  .crop-confirm:hover { background: #0e3a22; }
  .crop-cancel { font-size: 0.72rem; color: #555; background: none; border: none; cursor: pointer; }
  .crop-cancel:hover { color: #999; }

  /* ── History panel ── */
  .iter-card { background: #161618; border: 1px solid #1e1e20; border-radius: 7px; overflow: hidden; }

  .iter-head { display: flex; align-items: center; gap: 0.5rem; padding: 0.45rem 0.65rem; background: #131315; }
  .iter-num { font-size: 0.78rem; font-weight: 600; color: #666; }
  .iter-time { margin-left: auto; font-size: 0.68rem; color: #333; }

  .iter-shots { display: grid; grid-template-columns: 1fr 1fr; gap: 2px; padding: 0.4rem; }
  .iter-shots img { width: 100%; border-radius: 3px; background: #0a0a0b; }
  .diff-img { opacity: 0.85; }

  .iter-errors { padding: 0 0.5rem 0.4rem; }
  .iter-errors code {
    display: block; background: #2a1515; color: #f87171; padding: 0.2rem 0.4rem;
    border-radius: 3px; font-size: 0.7rem; font-family: monospace; white-space: pre-wrap; word-break: break-all; margin-top: 2px;
  }
  .iter-note { margin: 0 0.5rem 0.5rem; padding: 0.3rem 0.5rem; font-size: 0.72rem; color: #666; border-left: 2px solid #3b82f6; }

  /* ── Activity feed ── */
  .log-feed {
    overflow-y: auto; max-height: calc(100vh - 180px);
    padding: 0.3rem 0.2rem; display: flex; flex-direction: column; gap: 1px; font-size: 0.75rem;
  }

  .ev { display: flex; gap: 0.35rem; padding: 0.3rem 0.4rem; border-radius: 5px; align-items: flex-start; }
  .ev:hover { background: #161618; }

  .ev-ts { font-size: 0.66rem; color: #2e2e34; font-variant-numeric: tabular-nums; flex-shrink: 0; padding-top: 2px; min-width: 50px; }

  .ev-body { display: flex; flex-direction: column; gap: 0.25rem; min-width: 0; flex: 1; }

  .ev-tag { display: inline-block; font-size: 0.6rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; padding: 0.1rem 0.35rem; border-radius: 3px; width: fit-content; }
  .tag-info    { background: #1a2236; color: #60a5fa; }
  .tag-write   { background: #1a2a1a; color: #86efac; }
  .tag-img     { background: #2a1a2a; color: #d8b4fe; }
  .tag-diff    { background: #2a1a10; color: #fb923c; }
  .tag-live    { background: #0e2020; color: #2dd4bf; }
  .tag-model   { background: #1a2a1a; color: #4ade80; }
  .tag-warn    { background: #2a2010; color: #fbbf24; }
  .tag-gemini  { background: #1a2030; color: #38bdf8; }
  .tag-ok      { background: #0e2a1a; color: #34d399; }
  .tag-pad     { background: #1a1a2a; color: #a78bfa; }

  .ev-text  { color: #bbb; font-size: 0.75rem; }
  .ev-muted { color: #3a3a44; font-size: 0.7rem; }
  .ev-error { color: #f87171; font-size: 0.72rem; }

  .ev-arrow { font-weight: 700; color: #444; }
  .ev-arrow.ok { color: #22c55e; }

  .ev-tool-name { font-weight: 600; color: #ccc; font-size: 0.78rem; }
  .ev-args { color: #333; font-size: 0.68rem; white-space: pre-wrap; word-break: break-all; }

  .ev-status { font-size: 0.7rem; font-weight: 600; }
  .ev-cerr { color: #ef4444; font-size: 0.7rem; }

  .ev-img { max-width: 100%; border-radius: 4px; background: #0d0d0e; border: 1px solid #1e1e20; margin-top: 0.2rem; display: block; }
  .ev-diff-img { border-color: #3b1a1a; }

  .ev-thumbrow { display: flex; gap: 0.4rem; flex-wrap: wrap; margin-top: 0.2rem; }
  .ev-thumb-wrap { display: flex; flex-direction: column; align-items: center; gap: 0.1rem; }
  .ev-thumb-label { font-size: 0.6rem; color: #333; }

  .ev-prose { color: #666; line-height: 1.5; white-space: pre-wrap; word-break: break-word; font-size: 0.73rem; }

  .ev-console-errors { display: flex; flex-direction: column; gap: 2px; margin-top: 0.2rem; }
  .ev-console-errors code { display: block; background: #2a1515; color: #f87171; padding: 0.15rem 0.35rem; border-radius: 3px; font-size: 0.68rem; font-family: monospace; white-space: pre-wrap; word-break: break-all; }

  .ev-details { margin-top: 0.2rem; }
  .ev-details summary { cursor: pointer; color: #333; font-size: 0.68rem; }
  .ev-details pre { margin: 0.2rem 0 0; background: #0d0d0e; border: 1px solid #1e1e20; border-radius: 3px; padding: 0.4rem; font-size: 0.68rem; color: #555; white-space: pre-wrap; word-break: break-all; max-height: 120px; overflow-y: auto; }

  .ev-iter-sep { padding: 0.5rem 0 0.2rem; }
  .ev-sep-line { font-size: 0.67rem; font-weight: 600; color: #222; text-transform: uppercase; letter-spacing: 0.08em; }

  .ev-loop-start { border-left: 2px solid #3b82f6; }
  .ev-loop-end   { border-left: 2px solid #22c55e; }
  .ev-warn       { border-left: 2px solid #f59e0b; }
  .ev-gemini     { border-left: 2px solid #38bdf8; }
  .ev-model-text { border-left: 2px solid #4ade80; }
  .ev-screenshot { border-left: 2px solid #a855f7; }
  .ev-diff       { border-left: 2px solid #f97316; }
  .ev-current    { border-left: 2px solid #14b8a6; }

  /* ── Color swatches ── */
  .ev-swatches { display: flex; gap: 0.3rem; flex-wrap: wrap; margin-top: 0.3rem; }
  .ev-swatch-wrap { display: flex; flex-direction: column; align-items: center; gap: 0.1rem; cursor: default; }
  .ev-swatch { width: 24px; height: 24px; border-radius: 3px; border: 1px solid rgba(255,255,255,0.07); flex-shrink: 0; }
  .ev-swatch-hex { font-size: 0.54rem; color: #3a3a44; font-family: monospace; }
  .ev-swatch-pct { font-size: 0.5rem; color: #2e2e36; }

  /* ── Gemini critique expand ── */
  .ev-gemini-details { margin-top: 0.2rem; }
  .ev-gemini-details summary { cursor: pointer; color: #888; font-size: 0.73rem; line-height: 1.4; list-style: none; outline: none; }
  .ev-gemini-details summary::-webkit-details-marker { display: none; }
  .ev-gemini-details[open] summary { color: #555; }
  .ev-gemini-full { margin-top: 0.4rem; max-height: 320px; overflow-y: auto; padding-right: 0.25rem; border-left: 2px solid #1a3040; padding-left: 0.5rem; }

  /* ── Feedback drawer ── */
  .feedback-drawer {
    position: fixed; bottom: 0; left: 0; right: 0; height: 280px;
    background: #0e0e10; border-top: 1px solid #2a2a30;
    display: flex; flex-direction: column; z-index: 200;
    box-shadow: 0 -8px 32px rgba(0,0,0,0.6);
  }

  .fb-header {
    display: flex; align-items: center; gap: 1rem;
    padding: 0.55rem 1rem; border-bottom: 1px solid #1e1e22; flex-shrink: 0;
  }
  .fb-title { font-size: 0.8rem; font-weight: 700; color: #a78bfa; }
  .fb-hint { font-size: 0.72rem; color: #3a3a44; flex: 1; }
  .fb-close { background: none; border: none; color: #444; font-size: 1rem; cursor: pointer; padding: 0; line-height: 1; }
  .fb-close:hover { color: #999; }

  .fb-body { display: flex; gap: 0; flex: 1; overflow: hidden; }

  .fb-selections {
    width: 55%; border-right: 1px solid #1e1e22; overflow-y: auto;
    padding: 0.5rem 0.75rem; display: flex; flex-direction: column; gap: 0.25rem;
  }

  .fb-section-label { font-size: 0.65rem; font-weight: 700; color: #444; text-transform: uppercase; letter-spacing: 0.07em; display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.15rem; }
  .fb-clear-link { background: none; border: none; color: #333; font-size: 0.62rem; cursor: pointer; padding: 0; }
  .fb-clear-link:hover { color: #777; }

  .fb-el {
    display: flex; align-items: center; gap: 0.3rem; flex-wrap: wrap;
    background: #161618; border: 1px solid #1e1e20; border-radius: 4px; padding: 0.25rem 0.4rem;
    font-size: 0.7rem;
  }
  .fb-el-tag { color: #60a5fa; font-family: monospace; font-weight: 600; }
  .fb-el-attr { color: #a78bfa; font-family: monospace; font-size: 0.65rem; }
  .fb-el-text { color: #555; font-style: italic; font-size: 0.65rem; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .fb-el-rect { color: #333; font-size: 0.6rem; margin-left: auto; white-space: nowrap; }
  .fb-remove { background: none; border: none; color: #333; cursor: pointer; font-size: 0.8rem; padding: 0 0.1rem; line-height: 1; flex-shrink: 0; }
  .fb-remove:hover { color: #ef4444; }

  .fb-crops-row { display: flex; gap: 0.4rem; flex-wrap: wrap; }
  .fb-crop-thumb {
    position: relative; border: 1px solid #2a2a30; border-radius: 4px; overflow: hidden;
    width: 72px; flex-shrink: 0;
  }
  .fb-crop-thumb img { width: 100%; display: block; }
  .fb-crop-label { position: absolute; bottom: 0; left: 0; right: 0; background: rgba(0,0,0,0.7); color: #aaa; font-size: 0.55rem; padding: 0.1rem 0.2rem; text-align: center; }
  .fb-crop-remove {
    position: absolute; top: 2px; right: 2px; background: rgba(0,0,0,0.7); border: none;
    color: #ccc; font-size: 0.7rem; cursor: pointer; border-radius: 3px; padding: 0 0.2rem; line-height: 1.4;
  }
  .fb-crop-remove:hover { color: #ef4444; }

  .fb-empty { font-size: 0.72rem; color: #2e2e38; line-height: 1.6; margin: auto 0; padding: 0.5rem 0; }
  .fb-empty strong { color: #3a3a48; }

  .fb-query-col { flex: 1; display: flex; flex-direction: column; padding: 0.5rem 0.75rem; gap: 0.5rem; }
  .fb-textarea {
    flex: 1; background: #161618; border: 1px solid #1e1e20; border-radius: 6px;
    color: #e2e2e8; font-size: 0.78rem; font-family: inherit; padding: 0.5rem 0.65rem;
    resize: none; outline: none; line-height: 1.5;
  }
  .fb-textarea:focus { border-color: #a78bfa50; }

  .fb-actions { display: flex; align-items: center; gap: 0.75rem; flex-shrink: 0; }
  .fb-saved { font-size: 0.7rem; color: #22c55e; flex: 1; }
  .fb-saved code { color: #86efac; font-size: 0.68rem; }

  .fb-save-btn {
    font-size: 0.78rem; font-weight: 600; color: #0a0a0b;
    background: #a78bfa; border: none; border-radius: 6px;
    padding: 0.4rem 1rem; cursor: pointer; white-space: nowrap; flex-shrink: 0;
  }
  .fb-save-btn:hover:not(:disabled) { background: #c4b5fd; }
  .fb-save-btn:disabled { opacity: 0.35; cursor: default; }
</style>
