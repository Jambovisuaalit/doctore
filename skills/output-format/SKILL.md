---
name: output-format
description: Format Doctore sports-betting decisions into standardized BET, WATCH, PASS, BLOCKED, market-scan, and compact WhatsApp outputs. Use when the user asks for picks, vetosuositukset, a daily scan, a client-facing betting report, or a concise message containing odds, probability, EV, stake, confidence, and execution rules.
license: MIT
compatibility: Agent Skills filesystem. No external tools required.
metadata:
  author: doctore-sports
  version: "2.0.0"
  category: reporting
allowed-tools: Read
---

# Output format

Format only verified calculations and statuses. Do not create missing numbers for presentation.

1. Choose exactly one status per candidate: BET, WATCH, PASS, or BLOCKED.
2. Include decision timestamp, event start, book, executable odds, price timestamp, model version, model probability, no-vig probability, EV, edge, minimum price, and validation status.
3. Include Kelly inputs, final stake, units, bankroll percentage, binding cap, and correlation group for BET.
4. State a precise execution or recheck rule.
5. Use `references/templates.md` for full and compact templates.
