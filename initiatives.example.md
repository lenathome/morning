# Initiatives

This file is the source of truth for active engineering initiatives. The morning tool reads it, then layers GitHub PR / Linear issue data on top of the status you write below.

Update it during your weekly planning time. Each initiative is an H2 heading with a YAML block of structured fields followed by free-text status.

If neither `linear_team` nor `github` is set, the initiative appears in the brief with status only — no auto-pulled signal.

---

## Carbon factors v3

```yaml
owner: manny
status: in-progress
# linear_team: ENG  # add when we re-introduce Linear in v2
github:
  repos: [ekko-api, ekko-edge-api]
  pr_keywords: [carbon-factor, cf-v3]
target_date: 2026-06-30
```

Replacing v2 endpoints with the new factor model. Currently blocked on validation rules from Nature Positive. Manny also handling the docs.ekko.earth migration plan.

## Checkout SDK v2

```yaml
owner: etienne
status: in-review
github:
  repos: [ekko-sdk-mono, sdk-test-client]
  pr_keywords: [sdk-v2]
target_date: 2026-07-15
```

New embedded checkout flow. Major PR open for review since Monday — needs my sign-off on the merchant-config schema.

## ekko Hub admin redesign

```yaml
owner: design
status: not-started
target_date: 2026-08-31
```

Awaiting design exploration before engineering scope. No code yet — included so it appears in the brief at status only.
