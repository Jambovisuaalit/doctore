---
name: anti-bias-audit
description: Audit a Doctore betting candidate for forced action, recency bias, favorite bias, price anchoring, result chasing, confirmation bias, public-fade narratives, and unsupported causal stories. Use when approving any BET, when the user asks for a cold review of a pick, or when forced action and narrative bias must be checked.
license: MIT
compatibility: Agent Skills filesystem. No external tools required.
metadata:
  author: doctore-sports
  version: "2.0.0"
  category: governance
allowed-tools: Read
---

# Anti-bias audit

Apply this after valid EV calculations and before risk sizing.

1. Read `references/checklist.md`.
2. Mark every item `CLEAR`, `FLAG`, or `NOT APPLICABLE`.
3. A flag must identify the unsupported assumption and its effect on execution.
4. Return `PASS` or `BLOCKED` when a flag invalidates the model or data basis.
5. Never upgrade a candidate because the narrative is compelling.
