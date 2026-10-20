"""Bounded, read-only ComfyUI node compatibility probe.

Never submit prompts, launch a server or download model weights.
"""
from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

MAX_RESPONSE_BYTES = 8 * 1024 * 1024
OBJECT_INFO_URL = "http://127.0.0.1:8188/object_info"


def probe_nodes(template_path, *, opener=urlopen):
    try:
        with open(template_path, "r", encoding="utf-8") as stream:
            graph = json.load(stream)
        required = sorted({node["class_type"] for node in graph.values()})
        with opener(OBJECT_INFO_URL, timeout=5) as response:
            if response.status != 200:
                return {"status": "unavailable", "required": required}
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            return {"status": "invalid_response", "required": required}
        installed = json.loads(raw)
        if not isinstance(installed, dict):
            return {"status": "invalid_response", "required": required}
        missing = sorted(set(required) - set(installed))
        invalid_inputs = []
        # Links and dynamic widget values are not validated here.
        for node_id, node in graph.items():
            class_type = node["class_type"]
            if class_type in missing:
                continue
            info = installed.get(class_type)
            if not isinstance(info, dict) or not isinstance(info.get("input"), dict):
                return {"status": "invalid_response", "required": required}
            declared = info["input"]
            allowed = set()
            for section in ("required", "optional", "hidden"):
                fields = declared.get(section, {})
                if not isinstance(fields, dict):
                    return {"status": "invalid_response", "required": required}
                allowed.update(fields)
            for field in node.get("inputs", {}):
                if field not in allowed:
                    invalid_inputs.append({"node_id": node_id, "class_type": class_type, "input": field})
        status = "missing_nodes" if missing else "invalid_inputs" if invalid_inputs else "compatible"
        return {"status": status, "required": required,
                "missing": missing, "invalid_inputs": invalid_inputs}
    except (OSError, ValueError, KeyError, TypeError, HTTPError, URLError, TimeoutError):
        return {"status": "unavailable"}
