# Task Printer — Theming and Tailwind Unification Proposal

This document proposes a cohesive theming strategy for Task Printer using Tailwind CSS. The goals are to:
- Eliminate scattered, inline CSS per template and centralize styles.
- Make light/dark themes consistent and easy to toggle.
- Create reusable UI primitives (buttons, cards, banners, forms) via Jinja macros that apply standardized Tailwind utility classes.
- Keep runtime simple (Flask-only) while offering an optional, production-ready Tailwind build step that can be leveraged in Docker builds.

This plan is incremental: you can adopt the quick-start CDN approach first, then migrate to a build-time Tailwind pipeline without breaking the app.

---

## Quick Summary (What changed)

- Adopted Tailwind CSS (Option A, CDN) to replace page-scoped inline styles.
- Added a small `static/styles/app.css` for tokens and a few custom rules (spinner, base colors).
- Implemented cohesive UI macros in `templates/_components.html`:
  - `btn(label, href=None, variant, size, ...)` — unified buttons (primary, secondary, danger, outline, ghost).
  - `flash(category, message)` and `flash_messages(messages)` — standardized flash banners.
  - `card(title, subtitle, actions)` — consistent card header/body with optional actions.
  - `topbar(title, actions, show_theme_toggle)` — page-level header with actions and a dark-mode toggle.
- Unified dark mode on `<html class="dark">` with a single `window.toggleDarkMode()` in `base.html`. The toggle’s label sync is encapsulated in `topbar`.
- Converted `index.html`, `jobs.html`, `templates.html`, `loading.html`, and `setup.html` to Tailwind utilities; reduced and removed page-local `<style>` blocks.
- Standardized button styles across pages via the `btn` macro (replaced ad-hoc link/buttons).

---

## How to use the macros

Import needed macros at the top of a template:
```
{% from "_components.html" import topbar, btn, flash_messages, card %}
```

- Top bar:
```
{{ topbar(title="My Page", actions=[{'label':'Jobs','href':'/jobs','variant':'outline'}]) }}
```

- Buttons:
```
{{ btn("Save", variant="primary", type="submit") }}
{{ btn("Delete", variant="danger", onclick="confirmDelete()") }}
{{ btn("Docs", href="/docs", variant="outline", size="sm") }}
```

- Card:
```
{% call card(title="Settings", actions=[{'label':'Help','href':'/help','variant':'ghost'}]) %}
  ... body content ...
{% endcall %}
```

- Flashes:
```
{{ flash_messages(get_flashed_messages(with_categories=true)) }}
```

---

## Dark mode

- Strategy: Tailwind `dark` mode via `class` on `<html>`.
- Storage: preference in `localStorage` under `taskprinter:dark`. If missing, OS preference is respected at first load.
- Toggle: global `window.toggleDarkMode()` defined in `base.html`, with the topbar macro managing the label text.

---

## Option A (CDN) details

- `base.html` loads Tailwind CDN and configures `darkMode: 'class'`.
- `static/styles/app.css` provides a small layer of custom tokens (colors) and spinner animation.
- No Node build or purge required for development; for production, consider Option B (build step) to purge and minify CSS.

---

## Page migrations (high level)

- `index.html`: top actions unified; instructions and job banner styled with Tailwind; flashes via macro.
- `jobs.html`: table layout and actions unified; auto-refresh UI cleaned up.
- `templates.html`: action row buttons converted to `btn` macro for cohesion.
- `loading.html`: centered card + spinner styled via Tailwind/app.css.
- `setup.html`: replaced large inline styles with Tailwind; unified controls; wrapped content with `card`; bottom buttons use `btn` macro.

---

## Changelog (theming)

- Added Tailwind (CDN) in `base.html`; removed most inline styles from templates.
- Introduced `templates/_components.html` with cohesive macros: `btn`, `flash`, `flash_messages`, `card`, `topbar`.
- Switched dark mode to `<html class="dark">` with one toggle function and a label sync in `topbar`.
- Standardized buttons, flashes, and card headers across pages.
- Created `static/styles/app.css` for minimal tokens and spinner.

---

## Next steps (optional)

- Option B (Build): Add Tailwind build pipeline (`tailwind.config.js`, `static/styles/input.css`, and `static/styles/tailwind.css`) with purge/minify; integrate in Docker multi-stage build.
- Components: Add a simple `table` macro later to unify headings/cells across Jobs/Templates.
- Accessibility: Consider focus-visible states for all custom controls and ensure color contrast in dark mode.



## Overview

Today:
- Each template (`index.html`, `setup.html`, `jobs.html`, `templates.html`, `loading.html`) declares big `<style>` blocks and inline `style="..."` attributes.
- `base.html` includes minimal shared styles and does not pull in a framework.
- Dark mode is toggled by setting `body.dark-mode`, with ad hoc overrides across pages.

Proposal:
- Introduce Tailwind CSS for layout and styling.
- Move theme management to Tailwind’s `dark` class strategy: toggle `document.documentElement.classList.toggle('dark')` instead of `body.dark-mode`.
- Extract shared UI into Jinja macros to remove repetition and ensure consistency.
- Centralize any remaining custom CSS in `static/styles/app.css` and phase out `<style>` blocks from templates.
- Offer two installation modes:
  - Option A (no-build): Tailwind Play CDN for immediate unification without Node.
  - Option B (build-time): Proper Tailwind JIT compilation and purging in Docker or scripts for production-grade performance and CSP friendliness.


## Tailwind Setup

You can choose one of the following. We recommend Option B for production, Option A for quick unblocking.


### Option A — Quick Start (Tailwind Play CDN)

- Pros: No build step, fastest path to unify styles.
- Cons: Larger CSS at runtime; dynamic style injection can complicate strict CSP.

Add to `templates/base.html` in `<head>`:
- Tailwind CDN script
- A small config for dark mode and accent colors
- A link to `static/styles/app.css` for app-specific overrides

Example head additions:
- Add: `<script src="https://cdn.tailwindcss.com"></script>`
- Add: `<script>tailwind.config = { darkMode: 'class', theme: { extend: { colors: { brand: { DEFAULT: '#007bff', dark: '#0056b3' }}}}};</script>`
- Add: `<link rel="stylesheet" href="{{ url_for('static', filename='styles/app.css') }}">`

Dark mode:
- Replace existing JS toggle (which uses `body.dark-mode`) with toggling the `dark` class on the `<html>` element:
  - `document.documentElement.classList.toggle('dark')`
  - Store preference in localStorage (e.g., `taskprinter:dark`)

This gives you Tailwind utilities across all templates. You can then progressively replace inline `<style>` rules with Tailwind classes and minimal custom CSS tokens in `static/styles/app.css`.


### Option B — Production Build (Recommended)

- Pros: Small, purged CSS, CSP friendly, predictable output.
- Cons: Requires Node during build (not at runtime), some setup.

Files to add:
- `tailwind.config.js` at repo root
- `static/styles/input.css` with Tailwind directives
- Build script (shell or npm) to compile into `static/styles/tailwind.css`
- Reference `tailwind.css` and `app.css` in `base.html`

Proposed `tailwind.config.js`:
- content globs for Tailwind to scan are your templates
- enable `darkMode: 'class'`

Proposed `static/styles/input.css`:
- `@tailwind base;`
- `@tailwind components;`
- `@tailwind utilities;`

Compile:
- `npx tailwindcss -i ./static/styles/input.css -o ./static/styles/tailwind.css --minify`

Reference in `base.html`:
- `<link rel="stylesheet" href="{{ url_for('static', filename='styles/tailwind.css') }}">`
- `<link rel="stylesheet" href="{{ url_for('static', filename='styles/app.css') }}">`

Dockerfile (multi-stage) extension:
- Add a build stage to install Node, run Tailwind compile, and copy only the generated CSS into the final image.
- No Node needed in the runtime image.

CSP:
- This approach avoids dynamically injected styles from Play CDN and is more CSP-friendly.


## Centralizing Styles

We will do three things:
1. Stop using `<style>` blocks within templates.
2. Replace inline `style="..."` attrs with Tailwind utility classes.
3. Keep minimal project-specific CSS variables and non-utility styles in `static/styles/app.css`.


### Recommended `static/styles/app.css`

Use CSS custom properties for brand colors and consistent shadows, and add only “non-utility” project-specific classes (e.g., the spinner):

- Define tokens (brand colors, shadows) with CSS vars to support quick palette changes.
- Implement shared non-utility bits (spinner animation, receipt preview canvas base rules, print-friendly adjustments).
- Keep this file small and stable; rely on Tailwind classes wherever possible.

Example contents:
- Root-level variables: brand, brand-dark, surface, surface-dark, text, text-dark.
- `.spinner` animation keyframes.
- `.receipt-preview` base look (if necessary), but prefer Tailwind for layout.


## Base Layout and Theme Toggle

Standardize on Tailwind and class-based dark mode:

- `darkMode: 'class'` in Tailwind config (or via CDN config).
- Toggle `document.documentElement.classList.toggle('dark')`.
- Persist preference in `localStorage` (key: `taskprinter:dark`).
- On page load, read preference and set class. If missing, prefer OS theme via `prefers-color-scheme: dark`.


## Reusable UI With Jinja Macros

Create `templates/_components.html` with macros for common UI patterns:

- `flash_messages(messages)`: Display flash messages with consistent styling.
- `button(kind, attrs...)`: Primary, secondary, ghost, and danger buttons in one place.
- `card(title, subtitle, body)` or `card_header/body/footer` slots.
- `topbar(actions=...)`: Dark mode toggle, links to Jobs, Templates, Setup.

Why macros:
- DRY: consistent classes across pages.
- Easy to tweak styles in one place.
- Reduces inline HTML/JS duplication.

Usage:
- `{% from "_components.html" import button, flash_messages, card %}`
- Use `{{ button('primary', href='/jobs') }}` instead of inline `<a>` with hand-typed classes.


## Class Mapping (Guidelines)

Below is a mapping guide to replace current styles/inline CSS with Tailwind classes. You can apply this progressively.

- Page container: `max-w-[600px] mx-auto p-5` (adjust per page)
- Card container (centered-card): `bg-white dark:bg-slate-800 rounded-2xl shadow-lg max-w-[440px] mx-auto mt-14 p-8 flex flex-col items-center`
- Headings: `text-gray-800 dark:text-gray-100` + size utilities
- Labels: `block mb-2 font-semibold text-gray-600 dark:text-gray-200`
- Inputs: `w-full p-2.5 border-2 rounded-md text-sm bg-white text-gray-900 border-gray-300 focus:outline-none focus:border-brand dark:bg-slate-800 dark:text-gray-100 dark:border-slate-600`
- Textarea: same input base + `min-h-[200px]`
- Task input row: `flex items-stretch gap-2 h-12 mb-4`
- Remove task button: `inline-flex items-center justify-center w-12 h-full rounded-md bg-red-600 text-white hover:bg-red-700`
- “Add task” button: `w-full py-2.5 rounded-md bg-green-600 text-white hover:bg-green-700`
- Primary submit: `w-full py-4 rounded-md text-lg bg-brand text-white hover:bg-brand-dark`
- Topbar: `flex items-center justify-between gap-2 my-4 flex-wrap`
- Top buttons: `inline-flex items-center gap-1.5 rounded-full px-3.5 py-2 text-sm bg-brand text-white hover:bg-brand-dark`
- Ghost button: `inline-flex items-center gap-1.5 rounded-md px-3.5 py-2 text-sm border border-brand text-brand hover:bg-blue-50 dark:hover:bg-slate-700`
- Flash success: `rounded-md border-l-4 p-3 bg-green-50 border-green-600 text-green-800 dark:bg-slate-700 dark:text-green-300`
- Flash error: `rounded-md border-l-4 p-3 bg-red-50 border-red-600 text-red-800 dark:bg-slate-700 dark:text-red-300`
- Instructions panel: `rounded-md p-4 mb-5 border-l-4 bg-blue-50 border-blue-600 text-blue-900 dark:bg-slate-700 dark:text-blue-300`
- Jobs table: `w-full text-sm`, th/td: `border-b border-gray-200 dark:border-slate-700 text-left px-2.5 py-2`
- Status colors: `text-gray-600`, `text-blue-600`, `text-green-700`, `text-red-600` (with dark variants)
- Spinner: keep `.spinner` class in `app.css`, wrap with Tailwind layout classes where needed.

Note: Tailwind allows fine-tuned spacing without inline style attributes.


## Page-by-Page Migration Plan

1) base.html
- Add Tailwind (CDN or compiled CSS).
- Add `app.css`.
- Update `<body>` wrapper content to rely on Tailwind base classes. Lightly theme page background:
  - `bg-slate-50 text-slate-900 dark:bg-slate-900 dark:text-slate-100`
- Add a small inline script or `static/js/theme.js` to:
  - Apply dark class on load from localStorage or OS preference.
  - Provide `toggleDarkMode()` that toggles `document.documentElement.classList` and updates the button label.

2) index.html
- Remove the `<style>` block.
- Replace container and controls with Tailwind classes per “Class Mapping”.
- Replace job banner inline styles with Tailwind (`border-l-4`, `rounded`, color utilities).
- Use the components macros for flash, buttons, and topbar.

3) setup.html
- Remove `<style>`, use Tailwind for form controls, preview card, and button row.
- Keep canvas drawing logic; the styling of the canvas container can be Tailwind-based (`bg-white border rounded`).
- Convert radio/checkbox sizing to Tailwind utility classes (e.g., `h-3.5 w-3.5`).

4) jobs.html
- Replace table styling and “jobs-actions” with Tailwind utilities.
- Add status color utility classes per `status` value.

5) templates.html
- Replace header, actions, card, flash with component macros and Tailwind classes.
- Use Tailwind responsive utilities for meta hide/show on small screens.

6) loading.html
- Replace `.centered-card` with the common card macro or Tailwind classes.
- Keep `.spinner` class; ensure `app.css` defines the animation; layout with Tailwind.

7) Remove legacy dark-mode CSS
- Delete body.dark-mode specific rules once all pages use `.dark` variants in Tailwind.
- Keep a short deprecation period where both exist if you plan a phased rollout.


## File/Directory Changes

Add:
- static/styles/input.css (Option B only; contains @tailwind directives)
- static/styles/tailwind.css (Option B output; generated)
- static/styles/app.css (shared custom tokens and small non-utility CSS)
- templates/_components.html (Jinja macros for UI primitives)
- static/js/theme.js (optional; for theme toggle and localStorage)

Modify:
- templates/base.html (include Tailwind + app.css; dark mode toggle wiring; macro imports if desired)
- templates/index.html, templates/setup.html, templates/jobs.html, templates/templates.html, templates/loading.html (remove inline styles; add Tailwind classes; use macros)

Optional (build-time):
- tailwind.config.js (Option B)
- scripts/build_css.sh (Option B)
- Dockerfile (multi-stage build to compile Tailwind CSS)


## Dark Mode Implementation Details

Storage key:
- `taskprinter:dark` → "true" | "false"

On page load:
- If `taskprinter:dark` exists, honor it.
- Otherwise, check `window.matchMedia('(prefers-color-scheme: dark)').matches`.
- Set or remove `document.documentElement.classList.add('dark')` accordingly.

Toggle:
- `function toggleDarkMode() { const r = document.documentElement; const dark = r.classList.toggle('dark'); localStorage.setItem('taskprinter:dark', dark ? 'true' : 'false'); const btn = document.getElementById('darkModeBtn'); if (btn) btn.textContent = dark ? '☀️ Light Mode' : '🌙 Dark Mode'; }`

Notes:
- Update all templates to refer to this unified toggle and text.
- Remove page-specific dark-mode patches once migrated.


## Build and Docker (Option B)

Tailwind build script (examples):
- Script: `scripts/build_css.sh`
- Command: `npx tailwindcss -i ./static/styles/input.css -o ./static/styles/tailwind.css --minify`

tailwind.config.js (example keys):
- `darkMode: 'class'`
- `content: ['./templates/**/*.html']`
- `theme.extend.colors.brand = { DEFAULT: '#007bff', dark: '#0056b3' }`

Dockerfile idea:
- Stage 1: Node 18-alpine, copy `templates/`, `static/styles/input.css`, `tailwind.config.js`, run `npx tailwindcss …`
- Stage 2: Python runtime, copy `static/styles/tailwind.css` and app code only.

This ensures CSS is compiled during build and served statically at runtime.


## Theming via Variables (Optional)

If you need easy brand swaps without rebuilding:
- Keep brand and surface CSS vars in `app.css` and map Tailwind classes to those via utility “bridge” classes as needed.
- Alternatively, keep multiple Tailwind themes via a small set of additional classes toggled on `<html data-theme="...">` and a tiny layer of custom CSS that sets CSS vars per theme key.
- For now, a single theme with a brand color extension in Tailwind is sufficient. Add more later if needed.


## Testing and Rollout

- Start with Option A (CDN) to validate layouts quickly.
- Migrate template by template:
  - Remove `<style>` blocks.
  - Replace inline `style` attributes with Tailwind utilities.
  - Convert local ad-hoc classes to Tailwind utilities.
  - Adopt macros for buttons, cards, and flashes.
- Once all pages are migrated, choose Option B (build) for production environments.
- Verify:
  - Forms still submit and CSRF tokens remain intact.
  - Dark mode toggles correctly and persists across pages.
  - `/setup` preview canvas still renders correctly.
  - Jobs and Templates pages are responsive and consistent.

Performance:
- Option B yields compact CSS (purged) and fastest first paint.
- Option A is acceptable for internal/low-traffic deployments but should be revisited for CSP and payload size if external-facing.


## Definition of Done

- No template contains a `<style>` block.
- No inline `style="..."` attributes for layout/visual styling; Tailwind utilities are used instead.
- `base.html` includes Tailwind and `app.css`.
- Jinja macros exist for:
  - Buttons (primary, secondary, danger, ghost)
  - Card containers
  - Flash messages
  - Topbar
- Dark mode implemented via `<html class="dark">` strategy; toggle centralized in one place; no page-specific toggles remain.
- Option B build documented and optionally integrated into Dockerfile.
- AGENTS.md updated to mention the new theming approach and macro usage (follow-up PR).


## Appendix — Suggested Macro Signatures

- `button(kind='primary', href=None, type='button', extra_classes='')`
  - Kinds: primary, secondary, danger, ghost
- `flash_messages(messages)` → render Flask flashed messages consistently
- `card(title=None, body_block=None, extra_classes='')` or slot-style blocks
- `topbar(show_dark_toggle=True, actions=[('Jobs','/jobs'), ('Templates','/templates'), ('Settings','/setup')])`

These live in `templates/_components.html` and are imported where needed:
- `{% from "_components.html" import button, flash_messages, card, topbar %}`

You can iteratively add more macros as patterns emerge (tables, forms, banners).


---

By following this plan, you’ll unify the look and feel across Task Printer, simplify maintenance by centralizing styles and components, and gain a scalable path to future theming needs without bloating your Flask runtime.