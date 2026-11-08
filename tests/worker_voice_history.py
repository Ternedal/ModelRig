"""Regression tests for bounded, validated voice conversation history.

Run without ASR, TTS, Ollama or GPU:
    python tests/worker_voice_history.py
"""
import ast
from pathlib import Path
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "worker" / "app" / "voice_pipeline.py"


def _prior_from_source(history):
    """Execute the actual bounded helper without importing Voice backends."""
    module = ast.parse(SOURCE.read_text(encoding="utf-8"))
    helper = next(
        node for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "_bounded_voice_history"
    )
    converse = next(
        node for node in module.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "converse"
    )
    assignments = [
        node for node in ast.walk(converse)
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "prior"
                for target in node.targets)
    ]
    if len(assignments) != 1 or not isinstance(assignments[0].value, ast.Call):
        raise AssertionError("converse must call the bounded history helper")
    callee = assignments[0].value.func
    if not isinstance(callee, ast.Name) or callee.id != "_bounded_voice_history":
        raise AssertionError("converse must use _bounded_voice_history")
    namespace = {}
    isolated_module = ast.fix_missing_locations(ast.Module(body=[helper], type_ignores=[]))
    exec(compile(isolated_module, str(SOURCE), "exec"),
         {"__builtins__": {"isinstance": isinstance, "dict": dict,
                            "str": str, "reversed": reversed, "len": len}},
         namespace)
    return namespace["_bounded_voice_history"](history)


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

    def test_scanning_stops_after_twelve_valid_turns(self):
        class CountedHistory(list):
            scanned = 0
            def __reversed__(self):
                for value in super().__reversed__():
                    self.scanned += 1
                    if self.scanned > 12:
                        raise AssertionError("scanned beyond 12 valid recent turns")
                    yield value

        history = CountedHistory(
            [{"role": "user", "content": "old"}] * 50000
            + [{"role": "assistant", "content": str(i)} for i in range(12)]
        )
        self.assertEqual([item["content"] for item in _prior_from_source(history)],
                         [str(i) for i in range(12)])
        self.assertEqual(history.scanned, 12)


if __name__ == "__main__":
    unittest.main()
