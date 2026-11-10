# loidolt-theme work for inkthaw

Theme work that M7 to M10 depend on, split out so it can land in
[loidolt-theme](https://github.com/loidolt/loidolt-theme) ahead of time. Filed as
loidolt/loidolt-theme#33 to #48. Checked against
theme 0.10.1 (packages in the repo) / 0.11.1 (npm) on 2026-11-10.

Rule from PLAN.md §10.4 still applies: everything here must be generic, with no
inkthaw-specific code. Each task names an inkthaw use only to show why it exists.

## Already covered (no work)

- Layout: `Workspace` (sidebar, main, inspector), `Topbar`, `Sidebar`, `Drawer`, `Panel`.
- Page thumbnails: `Filmstrip`, `Thumbnail`. Flagged-page stepping: `RecordStepper`.
- Job list and status: `DataTable`, `ListRow`, `Progress`, `StatusDot`, `Badge`, `Toast`, `EmptyState`.
- Full-screen page view: `Lightbox` with pinch/wheel zoom and pan.
- Capacitor: system bars, back button, keyboard, haptics, safe areas, deep links, network, lifecycle.
- `hls.js` is already an optional peer dependency, so it doesn't bloat the UI bundle.
- Safe-area knobs `--ldt-safe-{top,right,bottom,left}` exist.

## A. Svelte components (needed by M7, web UI)

Ordered by how much the review screen depends on them.

1. **Inline zoomable image viewer with region overlays.** ([#33](https://github.com/loidolt/loidolt-theme/issues/33)) `Lightbox` is modal only; the review
   screen needs the page image *inside* the main pane. Zoom, pan, fit-to-width/height, and a
   `regions` prop (rectangles in image coordinates, each with id, variant and label) drawn on top
   and kept aligned through zoom. Region click/hover events and a `selectedRegionId` so the text
   side can highlight the matching block, and the reverse. Ideally `Lightbox` reuses the same zoom
   core.
   - Done when: catalog demo with 20+ regions stays aligned at every zoom level, keyboard zoom
     works, regions are reachable by keyboard and announced, axe passes.
2. **Resizable split for `Workspace`.** ([#34](https://github.com/loidolt/loidolt-theme/issues/34)) The inspector (or a new two-pane mode) needs a draggable
   divider with min/max, keyboard resizing (`role="separator"`, arrow keys) and an optional
   persisted size. Review is image | text side by side, and users will want to resize it.
   - Done when: drag and keyboard both work, size survives reload when a storage key is given,
     collapses to stacked panes on narrow screens.
3. **Dropzone.** ([#35](https://github.com/loidolt/loidolt-theme/issues/35)) `FileInput` has no drag-and-drop. Add a `Dropzone` (area target and an optional
   whole-window target) with `accept` filtering, multiple files, drag-over state, a rejection
   message for wrong types, and a click/keyboard fallback to the file picker. Its `onFiles` input
   should accept files from any source, so the Tauri file-drop adapter (C4) can feed it.
4. **Annotated text editor.** ([#36](https://github.com/loidolt/loidolt-theme/issues/36)) `Textarea` is plain. Review needs editable text where ranges can be
   marked (low-confidence words, rejoined hyphens, changes made by cleanup) with a variant and a
   tooltip, and those marks move correctly while the user types. Exposes the edited text and the
   remaining marks. Also: jump to next/previous mark. Plain text only, no rich text.
   - Possibly the largest task. Decide early whether it's a `contenteditable` component or a
     textarea with a mirrored highlight layer; the second is simpler and keeps native undo.
5. **Stage stepper.** ([#37](https://github.com/loidolt/loidolt-theme/issues/37)) A horizontal/vertical list of named steps with states (pending, running,
   done, skipped, failed) and optional per-step progress. Shows the pipeline stages for a job.
   `RecordStepper` is prev/next only, so this is new.
6. **Command and shortcut registry.** ([#38](https://github.com/loidolt/loidolt-theme/issues/38)) A small module: register commands (id, label, shortcut,
   handler, enabled), handle key events with platform-aware modifiers (Cmd vs Ctrl), and a way to
   list them (for a shortcut help dialog, and for C3's native menu). Review needs "next flagged
   page", "save and rebuild", "zoom".
7. **QR code display** ([#39](https://github.com/loidolt/loidolt-theme/issues/39)) (small, optional). Render a string as an accessible QR code with a text
   fallback and copy button. Generic; inkthaw uses it for pairing. Can stay in inkthaw if you'd
   rather not add a dependency to the theme.

## B. Styles (needed by M7, nice to have before)

1. **CSS-only use without Svelte.** ([#40](https://github.com/loidolt/loidolt-theme/issues/40)) Confirm `@loidolt/theme-styles` works in a plain HTML page
   and document it. Provide one bundled CSS file (tokens + base + dark-auto + the components
   inkthaw's report uses) that can be inlined, and fonts that can be embedded or fall back
   cleanly. Lets the Python-generated `report.html` match the web UI while staying one
   self-contained file.

## C. New package `@loidolt/theme-tauri` (needed by M8, macOS app)

Same pattern as `@loidolt/theme-capacitor`: Tauri plugins passed in, inert in a plain browser.
C1 first; the rest are independent of each other.

1. **Package skeleton.** ([#41](https://github.com/loidolt/loidolt-theme/issues/41)) Workspace package, build, `isTauri()` platform check, setup function,
   catalog page, release via changesets, peer dependencies on `@tauri-apps/api` 2.x and the
   plugins used below (all optional). A minimal example Tauri app in `examples/` to test against.
2. **Window chrome.** ([#42](https://github.com/loidolt/loidolt-theme/issues/42)) Overlay title bar: set `--ldt-safe-top` / `--ldt-safe-left` so content
   clears the macOS window buttons; add drag regions to `Topbar` (opt-in prop, e.g. `dragRegion`,
   that sets `data-tauri-drag-region` and keeps buttons clickable). Window background and
   appearance follow the theme's light/dark setting, with no white flash on launch.
3. **Native menu bar.** ([#43](https://github.com/loidolt/loidolt-theme/issues/43)) Build the macOS menu from the A6 command registry (labels, shortcuts,
   enabled state kept in sync). Depends on A6.
4. **Files.** ([#44](https://github.com/loidolt/loidolt-theme/issues/44)) Native open/save dialogs, and file drop onto the window delivered into A3's
   `Dropzone`. Depends on A3.
5. **Notifications.** ([#45](https://github.com/loidolt/loidolt-theme/issues/45)) OS notifications with permission handling ("book finished", "job failed").
6. **App lifecycle.** ([#46](https://github.com/loidolt/loidolt-theme/issues/46)) Single instance (second launch focuses the window and passes its
   arguments/files), deep links, and an optional tray icon with a menu (for watch mode).

## D. Capacitor additions (needed by M9, iOS)

PLAN.md §10.4 says the generic native pieces go to the theme; neither exists yet.

1. **Share sheet.** ([#47](https://github.com/loidolt/loidolt-theme/issues/47)) Share a file (EPUB) or URL via `@capacitor/share`, falling back to the Web
   Share API, then to a download. inkthaw uses it to send the EPUB to Books.
2. **File picker and saving.** ([#48](https://github.com/loidolt/loidolt-theme/issues/48)) Pick files (PDFs) natively, and save a downloaded file to the
   device via `@capacitor/filesystem`. Falls back to `FileInput`/download in a browser.

## Suggested order

| When | Tasks |
|---|---|
| Now (unblocks the M7 review screen) | A1, A2, A3, A4 |
| Before M7 ends | A5, A6, B1 (A7 optional) |
| Before M8 starts | C1, C2, then C3 to C6 |
| Before M9 starts | D1, D2 |

Pin exact theme versions in inkthaw's `app/package.json` and upgrade deliberately.
