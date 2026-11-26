#!/usr/bin/env python3
"""Build the tiny offline Piper voice that CI's frozen-worker check speaks with.

ci.yml's windows-worker-package job asks the frozen (PyInstaller) worker to synthesize one
sentence (#2275, v2.0.19 T4: piper-tts 1.8.0 inside the package). A real voice is 60 MB and has to
be downloaded; this one is a few hundred bytes, committed, and needs no network:

- The config is a normal Piper espeak config for Danish ("da"), with piper's own phoneme id map.
  Piper's real phonemizer, its bundled espeak-ng data and onnxruntime therefore all run, in the
  frozen exe, for a Danish sentence.
- The ONNX model has Piper's exact input/output contract (input, input_lengths, scales -> output
  [1, 1, T]) but no learned weights: it returns a 440 Hz tone, 256 samples per phoneme id. That
  proves the package can synthesize. It says nothing about voice quality, the GPU or the rig.

Regenerate (needs `pip install onnx piper-tts`):
    python tests/support/make_piper_ci_voice.py tests/fixtures/piper
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

NAME = "kaliv-ci-tone"
SAMPLE_RATE = 22050
HOP = 256


def build_model():
    import onnx
    from onnx import TensorProto, helper

    const = lambda name, dtype, values, dims=(): helper.make_node(  # noqa: E731
        "Constant", [], [name], value=helper.make_tensor(name + "_v", dtype, list(dims), values))
    nodes = [
        helper.make_node("Shape", ["input"], ["shape"]),
        const("one", TensorProto.INT64, [1]),
        helper.make_node("Gather", ["shape", "one"], ["count"], axis=0),
        const("hop", TensorProto.INT64, [HOP]),
        helper.make_node("Mul", ["count", "hop"], ["samples"]),
        helper.make_node("Cast", ["samples"], ["samples_f"], to=TensorProto.FLOAT),
        const("zero_f", TensorProto.FLOAT, [0.0]),
        const("one_f", TensorProto.FLOAT, [1.0]),
        helper.make_node("Range", ["zero_f", "samples_f", "one_f"], ["t"]),
        const("omega", TensorProto.FLOAT, [2.0 * math.pi * 440.0 / SAMPLE_RATE]),
        helper.make_node("Mul", ["t", "omega"], ["phase"]),
        helper.make_node("Sin", ["phase"], ["wave"]),
        const("amplitude", TensorProto.FLOAT, [0.3]),
        helper.make_node("Mul", ["wave", "amplitude"], ["audio"]),
        const("axes", TensorProto.INT64, [0, 1], dims=(2,)),
        helper.make_node("Unsqueeze", ["audio", "axes"], ["output"]),
    ]
    graph = helper.make_graph(
        nodes, NAME,
        inputs=[helper.make_tensor_value_info("input", TensorProto.INT64, [1, "phonemes"]),
                helper.make_tensor_value_info("input_lengths", TensorProto.INT64, [1]),
                helper.make_tensor_value_info("scales", TensorProto.FLOAT, [3])],
        outputs=[helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 1, "samples"])],
    )
    # Opset 13 and IR 8: old enough for any onnxruntime that piper-tts 1.x installs.
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)],
                              producer_name="kaliv-ci", producer_version="1")
    model.ir_version = 8
    onnx.checker.check_model(model)
    return model


def build_config() -> dict:
    from piper.phoneme_ids import DEFAULT_PHONEME_ID_MAP

    return {
        "dataset": NAME,
        "audio": {"sample_rate": SAMPLE_RATE, "quality": "x_low"},
        "espeak": {"voice": "da"},
        "language": {"code": "da_DK"},
        "inference": {"noise_scale": 0.667, "length_scale": 1, "noise_w": 0.8},
        "phoneme_type": "espeak",
        "phoneme_id_map": DEFAULT_PHONEME_ID_MAP,
        "num_symbols": 1 + max(i for ids in DEFAULT_PHONEME_ID_MAP.values() for i in ids),
        "num_speakers": 1,
        "speaker_id_map": {},
        "hop_length": HOP,
        "piper_version": "1.8.0",
    }


def main(out_dir: str) -> int:
    import onnx

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    onnx.save(build_model(), out / f"{NAME}.onnx")
    (out / f"{NAME}.onnx.json").write_text(json.dumps(build_config(), indent=2, ensure_ascii=False) + "\n",
                                           encoding="utf-8")
    print(f"wrote {out / NAME}.onnx and .onnx.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures/piper"))
