# Freshness policy

Apply the strictest relevant limit. Configuration can be stricter than these defaults.

| Input | Default maximum age |
|---|---:|
| Pregame executable price | 5 minutes |
| In-play price | 15 seconds |
| Event status | 2 minutes near start |
| Confirmed lineup or active roster | 30 minutes near start |
| Starting pitcher or goalie status | 30 minutes near start |
| Weather | 60 minutes near start |
| Injury news | 60 minutes, shorter near start |
| Portfolio exposure | 60 seconds before sizing |

Return `BLOCKED` when a critical value is stale and cannot be refreshed. Return `WATCH` only when a known refresh trigger can resolve the condition before execution.
