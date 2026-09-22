# Consciousness Core experiments

This directory contains **non-runtime** reference implementations used to prove
Consciousness Core contracts before any product integration exists.

Current content:

- `mock_thought_engine.py` — deterministic C3 ThoughtEngine reference.\n- `model_swap_eval.py` — reproducible receipt proving same SelfState across a weak/strong engine swap.

Rules:

- no network access;
- no model-provider SDK;
- no tools or Agent 3 execution;
- no Memory 4 write;
- no scheduler/background loop;
- no Person/Profile mutation;
- no BodyRig/VoiceRig mutation;
- no production activation.

Moving code from this directory into worker/backend runtime requires a separate
reviewed slice. C0–C3 completion does not authorize that move.
