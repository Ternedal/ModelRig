"""Bounded, read-only ComfyUI node compatibility probe.

Never submit prompts, launch a server or download model weights.
"""
from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_TEMPLATE_BYTES = 2 * 1024 * 1024
OBJECT_INFO_URL = "http://127.0.0.1:8188/object_info"


def probe_nodes(template_path, *, opener=urlopen):
    try:
        with open(template_path, "rb") as stream:
            raw_template = stream.read(MAX_TEMPLATE_BYTES + 1)
        if len(raw_template) > MAX_TEMPLATE_BYTES:
            return {"status": "invalid_template"}
        try:
            graph = json.loads(raw_template)
        except (ValueError, UnicodeError):
            return {"status": "invalid_template"}
        if not isinstance(graph, dict) or not graph or any(
            not isinstance(node, dict) or not isinstance(node.get("class_type"), str)
            or not isinstance(node.get("inputs", {}), dict) for node in graph.values()
        ):
            return {"status": "invalid_template"}
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
        invalid_choices = []
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
                    continue
                value = node["inputs"][field]
                # ComfyUI enumerated widget options include available checkpoint
                # filenames. Literal selections must match; placeholders and links
                # are intentionally deferred until request binding/runtime.
                if isinstance(value, str) and value.startswith("__KALIV_VIDEO_"):
                    continue
                if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and value[0] in graph and type(value[1]) is int:
                    continue
                definition = next((declared[section][field] for section in ("required", "optional", "hidden")
                                   if field in declared.get(section, {})), None)
                if (isinstance(definition, list) and definition
                        and isinstance(definition[0], list)
                        and isinstance(value, str) and value not in definition[0]):
                    invalid_choices.append({"node_id": node_id, "class_type": class_type, "input": field})
        status = ("missing_nodes" if missing else "invalid_inputs" if invalid_inputs
                  else "invalid_choices" if invalid_choices else "compatible")
        return {"status": status, "required": required,
                "missing": missing, "invalid_inputs": invalid_inputs,
                "invalid_choices": invalid_choices}
    except (OSError, ValueError, KeyError, TypeError, UnicodeError, HTTPError, URLError, TimeoutError):
        return {"status": "unavailable"}
