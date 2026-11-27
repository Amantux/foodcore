# Accessibility acceptance checklist — quick actions

Single source of truth for the one-tap **edit / undo / re-log** quick actions
(the ideas 9 / 16 flows). Implementation PRs for those ideas must satisfy this
checklist, and reviewers must verify the keyboard-only and 200% zoom pass is
documented in the PR before merge.

## Checklist

- [ ] **Quick actions are real buttons.** Every quick action (edit, undo, re-log)
      is a real `<button>`, not a `<div>` or icon-only element.
  - **How to check:** inspect the rendered DOM / component source; every
      quick-action handler should be bound to a native button.

- [ ] **Quick actions have names.** Every quick action has a text label or
      `aria-label` naming the action and the entry, e.g.
      `Undo last entry: oatmeal with banana`.
  - **How to check:** each quick action's accessible name includes both the
      action and the entry it refers to.

- [ ] **Undo/redo confirmations are announced.** Undo/redo confirmations use
      `role="status"` or `aria-live="polite"`.
  - **How to check:** trigger undo/redo and confirm the confirmation renders in
      a live region.

- [ ] **Focus returns to the action button after undo/re-log.**
  - **How to check:** after undo or re-log, focus is back on the originating
      quick-action button.

- [ ] **No state is signalled by colour alone** — icon + text.
  - **How to check:** added / changed / removed states show icon + text, not
      colour alone.

- [ ] **Touch targets are at least 44×44px.**
  - **How to check:** computed size of quick-action buttons is ≥ 44×44px.

- [ ] **Keyboard-only and 200% zoom pass, verified and documented in the PR.**
  - **How to check:** run the keyboard-only pass (Tab / Enter / Space, no mouse)
      and the 200% zoom pass; both must pass, and the results documented in the
      PR.

- [ ] **This checklist is the single source of truth** for these flows, and
      idea 16/9 implementation PRs reference it.
  - **How to check:** implementation PRs for ideas 9/16 link to or quote this
      checklist, and the reviewer gate requires its items be satisfied.

Each item is verifiable by a person or a test.
