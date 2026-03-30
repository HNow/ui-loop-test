---
name: No Tailwind - plain CSS only
description: User wants Svelte components and generated HTML to use plain CSS, not Tailwind
type: feedback
---

Use plain CSS only — `<style>` blocks in Svelte, inline `<style>` in generated HTML.

**Why:** User preference. "Avoid using Tailwind, I want components written in Svelte with plain CSS."

**How to apply:** No Tailwind CDN links, no utility class names (`flex`, `text-sm`, etc.) in any Svelte file or generated HTML. Use CSS custom properties and plain selectors.
