# Accessibility — Phase 10 audit pass

Scope audited by hand (code inspection + computed contrast from the
design tokens): the `/start` wizard, the report page, the chat panel,
the institute dashboard, plus the shared UI kit (Modal, Tabs, Stepper,
Field) and both shells. There is no automated a11y test runner in this
repo and no screen reader was available in the build environment —
items that genuinely need one are listed under "Known remaining gaps"
rather than claimed as verified.

## Fixes made in this pass

1. **Modal focus management (both dialogs).** `components/ui/modal.tsx`
   had no focus handling at all; `components/motion.tsx`'s Modal had
   Escape + initial focus only. Both now: move focus into the dialog on
   open, trap Tab/Shift+Tab inside, close on Escape, and restore focus
   to the opener on close.
2. **Tabs keyboard pattern (both implementations).**
   `components/ui/tabs.tsx` and the `Tabs` in `components/ui.tsx` had
   `role="tab"` buttons with click-only operation and every tab in the
   tab order. Both now use roving tabindex (only the active tab is
   tabbable) with ArrowLeft/ArrowRight (move + activate), Home and End.
3. **Stepper current step.** `components/ui/stepper.tsx` now sets
   `aria-current="step"` on the current step (the wizard's progress was
   previously visual-only).
4. **Chat announcements.** The chat turn list is now
   `role="log" aria-live="polite"`, so assistant replies are announced;
   the input already had an sr-only label and the send button is a real
   submit button (Enter works — verified in code).
5. **Icon-only buttons.** The announcement dismiss ("×") button and the
   collapsed-sidebar feedback button in `app-shell.tsx` had no
   accessible name (title only / none); both now carry `aria-label`
   (new `p10_dismiss` key in EN/TA/HI). Other shell icon buttons
   (sign-out, about, sidebar toggle, language) already had labels.
6. **Muted-text contrast.** `--color-text-tertiary` was `#909090`:
   4.50:1 on bg-3 (borderline) and **3.56:1 on bg-4 — a WCAG AA fail**
   for the small text it styles. Brightened to `#a8a8a8` (see table).

## Measured contrast ratios (computed from token values)

Relative-luminance ratios per WCAG 2.x, computed from the hex values in
`frontend/app/globals.css` + `frontend/styles/tokens.css`:

| Pair | Ratio | AA normal (≥4.5) |
|---|---|---|
| dark fg `#ffffff` on bg `#0f0f0f` | 19.17:1 | pass |
| dark fg-2 `#9a9a9a` on bg `#0f0f0f` | 6.81:1 | pass |
| dark fg-2 `#9a9a9a` on surface `#1a1a1a` | 6.19:1 | pass |
| dark fg-2 `#9a9a9a` on panel `#1f1f1f` | 5.86:1 | pass |
| dark fg-2 `#9a9a9a` on bg-3 `#2a2a2a` | 5.10:1 | pass |
| dark fg-3 `#909090` on bg-3 `#2a2a2a` (BEFORE) | 4.50:1 | borderline |
| dark fg-3 `#909090` on bg-4 `#3a3a3a` (BEFORE) | 3.56:1 | **fail** |
| dark fg-3 `#a8a8a8` on bg `#0f0f0f` (AFTER) | 8.06:1 | pass |
| dark fg-3 `#a8a8a8` on bg-3 `#2a2a2a` (AFTER) | 6.04:1 | pass |
| dark fg-3 `#a8a8a8` on bg-4 `#3a3a3a` (AFTER) | 4.78:1 | pass |
| dark accent `#00d4aa` on bg `#0f0f0f` | 10.04:1 | pass |
| dark gold `#e6a82c` on bg `#0f0f0f` | 9.13:1 | pass |
| dark destructive `#e86868` on bg-3 `#2a2a2a` | 4.52:1 | pass |
| dark success `#22c55e` on bg `#0f0f0f` | 8.41:1 | pass |
| light fg `#1a1a1a` on bg `#ffffff` | 17.40:1 | pass |
| light muted `#4b5563` on bg `#ffffff` | 7.56:1 | pass |
| light muted `#4b5563` on surface `#f6f6f4` | 6.98:1 | pass |
| light accent-ink `#047857` on `#ffffff` | 5.48:1 | pass |
| light success `#15803d` / warning `#b45309` on `#ffffff` | 5.02:1 | pass |
| light danger `#b91c1c` on `#ffffff` | 6.47:1 | pass |

## Checklist (audited surfaces)

- [x] Focus order follows the visual order on wizard, report, chat,
      institute views (single-column flows, native controls).
- [x] Modals trap focus, Escape closes, focus restored (both dialogs).
- [x] Every icon-only button on the audited surfaces has an
      `aria-label` (shell toggles, sign-out, about, dismiss, modal
      close, feedback rating radios use `aria-label="n / 5"`).
- [x] Form fields are labelled: wizard fields use `htmlFor`/`id`
      pairs and fieldset+legend radio groups with real radio inputs;
      chat input has an sr-only label; institute `Field` wraps its
      control in a `<label>` (implicit association); login fields use
      `htmlFor`/`id`.
- [x] Muted text meets WCAG AA on every surface it renders on (table
      above, after the fg-3 fix).
- [x] Tabs: roving tabindex + arrow/Home/End operation.
- [x] Stepper exposes the current step (`aria-current="step"`).
- [x] Chat: Enter submits, log region announces replies, errors use
      `role="alert"`.
- [x] Wizard Back/Next/Submit are native buttons (keyboard operable,
      disabled states real `disabled` attributes).
- [x] Touch targets on the audited kit are ≥44 px (Modal close, Tabs).

## Keyboard map

| Widget | Keys |
|---|---|
| Modal / dialog | Tab / Shift+Tab cycle inside · Esc closes · focus returns to opener |
| Tabs (kit + ui.tsx) | Tab enters on the active tab · ←/→ move + activate · Home/End first/last |
| Wizard | Tab through fields · Space/←/→ on radio groups (native) · Enter submits forms |
| Chat | Tab to input · Enter sends |
| Stepper | Not focusable itself (status only, `aria-current` announced) |
| Sidebar / nav | Native links/buttons, Tab order = visual order |

## Known remaining gaps (not verified / not fixed here)

- **Screen-reader verification** of the full wizard → report → chat
  flow (NVDA/VoiceOver) has NOT been done — no screen reader exists in
  the build environment. The semantics above are code-level correct,
  but announcement quality (e.g. the Stepper list, motion-animated
  content) needs a real AT pass before any "accessible" claim is made
  to users.
- Tabs do not wire `aria-controls`/`tabpanel` ids — panels are not
  separate DOM regions in these views today (content swaps in place),
  so the tablist pattern is used without panel linkage.
- Motion/animation: `prefers-reduced-motion` handling exists for the
  low-bandwidth mode gates only; a dedicated reduced-motion audit of
  the shell animations was out of scope for this pass.
- Focus-visible styling relies on the browser default + component
  ring utilities; a unified `:focus-visible` token pass remains open.
