"""Regression tests for bounded, validated voice conversation history.

Run without ASR, TTS, Ollama or GPU:
    python -m unittest tests/worker_voice_history.py
"""
import ast
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "worker" / "app" / "voice_pipeline.py"


def _prior_from_source(history):
    """Execute the actual prior-history expression without importing voice backends."""
    module = ast.parse(SOURCE.read_text(encoding="utf-8"))
    converse = next(
        node for node in module.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "converse"
    )
    assignment = next(
        node for node in ast.walk(converse)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "prior"
                for target in node.targets)
    )
    expression = ast.Expression(body=assignment.value)
    return eval(compile(ast.fix_missing_locations(expression), str(SOURCE), "eval"),
                {"__builtins__": {"isinstance": isinstance, "str": str, "dict": dict}},
                {"history": history})


class VoiceHistoryTests(unittest.TestCase):
    def test_invalid_trailing_entries_do_not_evict_valid_history(self):
        history = [{"role": "user", "content": "blå elefant"}]
        history += [{"role": "system", "content": "ignored"}] * 12
        history += [{"role": "assistant", "content": ""}]
        self.assertEqual(_prior_from_source(history),
                         [{"role": "user", "content": "blå elefant"}])

    def test_last_twelve_valid_turns_remain_ordered(self):
        history = [{"role": "user", "content": str(i)} for i in range(15)]
        history.insert(10, {"role": "tool", "content": "ignore"})
        self.assertEqual([item["content"] for item in _prior_from_source(history)],
                         [str(i) for i in range(3, 15)])

    def test_invalid_shapes_and_content_length(self):
        history = [None, "bad", {"role": "user", "content": None},
                   {"role": "system", "content": "inject"},
                   {"role": "assistant", "content": "   "},
                   {"role": "assistant", "content": "x" * 5000}]
        self.assertEqual(_prior_from_source(history),
                         [{"role": "assistant", "content": "x" * 4000}])


if __name__ == "__main__":
    unittest.main()
