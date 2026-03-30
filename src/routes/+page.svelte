<script>
  import { onMount } from 'svelte';

  let components = [];
  let loading = true;
  let error = null;
  let showNewModal = false;
  let newComponentName = '';
  let newComponentRef = '';

  onMount(async () => {
    await loadComponents();
  });

  async function loadComponents() {
    loading = true;
    try {
      const res = await fetch('/api/components');
      const data = await res.json();
      components = (data.components || []).filter(c => c.status !== 'deleted');
    } catch (e) {
      error = e.message;
    }
    loading = false;
  }

  async function createComponent() {
    if (!newComponentName.trim()) return;
    
    try {
      const res = await fetch('/api/components', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: newComponentName,
          reference: newComponentRef || null
        })
      });
      const data = await res.json();
      if (data.success) {
        showNewModal = false;
        newComponentName = '';
        newComponentRef = '';
        await loadComponents();
      }
    } catch (e) {
      error = e.message;
    }
  }

  function statusColor(status) {
    switch (status) {
      case 'done': return '#22c55e';
      case 'stuck': return '#ef4444';
      case 'iterating': return '#f59e0b';
      default: return '#6b7280';
    }
  }

  function formatDate(dateStr) {
    if (!dateStr) return '';
    const d = new Date(dateStr);
    return d.toLocaleDateString() + ' ' + d.toLocaleTimeString().slice(0, 5);
  }
</script>

<svelte:head>
  <title>UI Cloner</title>
</svelte:head>

<div class="root">
  <header>
    <div class="header-content">
      <h1>UI Cloner</h1>
      <p class="sub">Clone UI components from reference screenshots</p>
    </div>
    <button class="new-btn" onclick={() => showNewModal = true}>
      + New Component
    </button>
  </header>

  <main>
    {#if loading}
      <p class="empty">Loading...</p>
    {:else if error}
      <p class="error">{error}</p>
    {:else if components.length === 0}
      <div class="empty-state">
        <p>No components yet.</p>
        <p class="hint">Create a new component to start cloning a UI.</p>
      </div>
    {:else}
      <div class="components">
        {#each components as comp}
          <a class="card" href="/component/{comp.id}">
            <div class="card-header">
              <span class="name">{comp.name}</span>
              <span class="status" style="color: {statusColor(comp.status)}">
                {comp.status}
              </span>
            </div>
            <div class="card-meta">
              <span>{comp.iteration_count || 0} iterations</span>
              {#if comp.best_ssim}
                <span>SSIM: {comp.best_ssim.toFixed(3)}</span>
              {/if}
            </div>
            <div class="card-time">
              {formatDate(comp.updated_at)}
            </div>
          </a>
        {/each}
      </div>
    {/if}
  </main>
</div>

{#if showNewModal}
  <div class="modal-overlay" onclick={() => showNewModal = false}>
    <div class="modal" onclick={(e) => e.stopPropagation()}>
      <h2>New Component</h2>
      <label>
        Name
        <input type="text" bind:value={newComponentName} placeholder="MyComponent">
      </label>
      <label>
        Reference Image (optional path)
        <input type="text" bind:value={newComponentRef} placeholder="ui-inspo/image.png">
      </label>
      <div class="modal-actions">
        <button onclick={() => showNewModal = false}>Cancel</button>
        <button class="primary" onclick={createComponent}>Create</button>
      </div>
    </div>
  </div>
{/if}

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
    margin-bottom: 3rem;
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

  .new-btn {
    background: #3b82f6;
    color: white;
    border: none;
    padding: 0.75rem 1.5rem;
    border-radius: 8px;
    font-weight: 500;
    cursor: pointer;
    transition: background 0.15s;
  }

  .new-btn:hover {
    background: #2563eb;
  }

  .components {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 1rem;
  }

  .card {
    background: #111113;
    border: 1px solid #222;
    border-radius: 12px;
    padding: 1.25rem 1.5rem;
    text-decoration: none;
    color: inherit;
    transition: border-color 0.15s, transform 0.1s;
  }

  .card:hover {
    border-color: #3b82f6;
    transform: translateY(-2px);
  }

  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.75rem;
  }

  .name {
    font-weight: 600;
    font-size: 1.1rem;
  }

  .status {
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .card-meta {
    display: flex;
    gap: 1rem;
    font-size: 0.85rem;
    color: #888;
  }

  .card-time {
    margin-top: 0.5rem;
    font-size: 0.75rem;
    color: #555;
  }

  .empty-state {
    text-align: center;
    padding: 4rem 2rem;
    color: #666;
  }

  .hint {
    font-size: 0.9rem;
    color: #555;
  }

  .error {
    color: #ef4444;
  }

  /* Modal */
  .modal-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.7);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 100;
  }

  .modal {
    background: #111113;
    border: 1px solid #333;
    border-radius: 12px;
    padding: 2rem;
    min-width: 400px;
  }

  .modal h2 {
    margin: 0 0 1.5rem;
  }

  .modal label {
    display: block;
    margin-bottom: 1rem;
    font-size: 0.85rem;
    color: #888;
  }

  .modal input {
    display: block;
    width: 100%;
    margin-top: 0.5rem;
    padding: 0.75rem;
    background: #1a1a1c;
    border: 1px solid #333;
    border-radius: 6px;
    color: #e2e2e8;
    font-size: 1rem;
  }

  .modal-actions {
    display: flex;
    justify-content: flex-end;
    gap: 0.75rem;
    margin-top: 1.5rem;
  }

  .modal-actions button {
    padding: 0.6rem 1.25rem;
    border-radius: 6px;
    border: 1px solid #333;
    background: #1a1a1c;
    color: #e2e2e8;
    cursor: pointer;
  }

  .modal-actions .primary {
    background: #3b82f6;
    border-color: #3b82f6;
  }
</style>
