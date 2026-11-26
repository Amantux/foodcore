# Release checklist — diary undo / re-log gates

One-page release checklist for the diary's undo and re-log surface. This document
is the **single source of truth** for the three pre-release gates a diary-bearing
build must clear before it ships.

## Owner attestation — not CI-enforced

> **The release gates are owner-attested, not CI-enforced.** The owner of the
> diary-bearing release verifies each gate below and attests to it before the
> release ships. **CI is not wired for this yet** — there is no automated job or
> check enforcing any of these gates, and the existing CI pipeline (`ruff check .`
> plus `python -m pytest -q`) is unchanged by this checklist. Until that wiring
> exists, these gates are a human, owner-held process gate: a green CI run says
> nothing about them.

### Attestation step — in the PR, not in CI

Before the release may proceed, the **PR author / owner must attest, in the PR**,
that gates (a), (b) and (c) are green, **quoting this doc**. The attesting author
states the gate(s) they verified and quotes the corresponding text from this
checklist, then attests before the release ships.

Until an automated check exists, this owner-held attestation — made in the PR —
is the process gate: a green CI run says nothing about it.

## Gate (a) — Manual diary works end-to-end

The diary's manual flow — log, edit, undo — works end-to-end on a real device.

- **Verification method:** the owner manually logs, edits, and undoes a diary
  entry and confirms it round-trips (log → edit → undo leaves the diary in the
  expected state).

## Gate (b) — Undo / re-log invariant tests pass

The undo / re-log surface holds its invariants.

- **Precondition:** idea 31 — the undo/re-log invariant-test task. **Idea 31 is a
  precondition for this gate**: the invariant-test suite for the undo/re-log
  surface must pass before gate (b) can be attested.
- **Verification method:** run the invariant-test suite for the undo/re-log
  surface and confirm it passes (`python -m pytest -q` over the diary
  undo/re-log tests).

## Gate (c) — Undo is device-local

Undo state stays on the device — no network / sync round-trip.

- **Verification method:** verify the undo state stays on the device; the undo
  path must not round-trip through network / sync.

## Sign-off

All three gates verified and owner-attested → the release may proceed.
