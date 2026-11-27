## Description

<!-- What does this PR change, and why? -->

## Changes

<!-- What behaviour, API, or data changed? -->

## Checklist

- [ ] Tests pass: `python -m pytest -q` and `ruff check .`.

## Accessibility — required for PRs touching the one-tap edit / undo / re-log flows

Required for implementation PRs that touch the one-tap **edit / undo / re-log**
quick-action flows (ideas 9 / 16). Skip this section for PRs that do not touch
those flows.

Single source of truth: [`docs/a11y-quick-actions.md`](docs/a11y-quick-actions.md).

Quoting the checklist from [`docs/a11y-quick-actions.md`](docs/a11y-quick-actions.md):

- [ ] **Quick actions are real buttons.** Every quick action (edit, undo, re-log) is a real `<button>`, not a `<div>` or icon-only element.
- [ ] **Quick actions have names.** Every quick action has a text label or `aria-label` naming the action and the entry, e.g. `Undo last entry: oatmeal with banana`.
- [ ] **Undo/redo confirmations are announced.** Undo/redo confirmations use `role="status"` or `aria-live="polite"`.
- [ ] **Focus returns to the action button after undo/re-log.**
- [ ] **No state is signalled by colour alone** — icon + text.
- [ ] **Touch targets are at least 44×44px.**
- [ ] **Keyboard-only and 200% zoom pass verified and documented in the PR.**
- [ ] **This checklist is the single source of truth** for the one-tap quick-action flows, and idea 16 / 9 implementation PRs reference it.

> **Reviewer gate:** before merge, a reviewer must verify that the keyboard-only and
> 200% zoom pass is documented in the PR before merge.
