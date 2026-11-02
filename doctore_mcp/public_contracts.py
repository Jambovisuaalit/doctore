"""Expose the existing canonical JSON contracts as self-contained MCP input schemas.

The canonical JSON Schemas remain authoritative for runtime validation. This
module only inlines local $defs references for the public Pydantic/FastMCP
tools/list surface. It does not change the decision engine or risk policy.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .runtime import REPO

import json


CONTRACT_FILES = {
    "model": "model-output.schema.json",
    "market": "market-snapshot.schema.json",
    "portfolio": "portfolio-state.schema.json",
    "policy": "risk-policy.schema.json",
    "artifact": "probability-prediction.schema.json",
}


def exposed_contract(name: str) -> dict[str, Any]:
    """Return a complete inline JSON Schema for one canonical input object."""
    if name not in CONTRACT_FILES:
        raise KeyError(name)
    document = json.loads((REPO / "contracts" / CONTRACT_FILES[name]).read_text(encoding="utf-8"))
    definitions = document.get("$defs", {})

    def expand(node: Any) -> Any:
        if isinstance(node, list):
            return [expand(value) for value in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            ref = node["$ref"]
            if not ref.startswith("#/$defs/"):
                raise ValueError(f"external contract reference not allowed: {ref}")
            key = ref[len("#/$defs/"):]
            if key not in definitions:
                raise ValueError(f"missing contract definition: {key}")
            replacement = deepcopy(definitions[key])
            replacement.update({k: v for k, v in node.items() if k != "$ref"})
            return expand(replacement)
        return {key: expand(value) for key, value in node.items() if key not in {"$schema", "$id", "$defs"}}

    return expand(document)
