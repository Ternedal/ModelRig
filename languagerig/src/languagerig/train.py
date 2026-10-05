"""Optional one-GPU QLoRA runner. Planning needs no torch or model download."""
from __future__ import annotations

import importlib.util
import importlib.metadata
import json
import math
import os
from pathlib import Path

from .core import LanguageRigError, digest, now, read_json, write_json
from .corpus import verify_dataset

DEFAULTS = {
    "model_id": "danish-foundation-models/munin-ministral3-8B",
    "model_revision": "main", "max_seq_length": 1024, "lora_rank": 16,
    "learning_rate": 0.00002, "epochs": 1.0, "max_steps": 100,
    "gradient_accumulation_steps": 16, "save_steps": 20, "seed": 42,
}


def training_plan(config_path: Path) -> dict:
    supplied = read_json(config_path)
    if set(supplied) - set(DEFAULTS) - {"dataset", "output_dir"}:
        raise LanguageRigError("Unknown training configuration fields.")
    config = {**DEFAULTS, **supplied}
    if not config.get("dataset") or not config.get("output_dir"):
        raise LanguageRigError("Training config needs dataset and output_dir.")
    for key in ("dataset", "output_dir"):
        config[key] = str((config_path.parent / config[key]).resolve())
    for key in ("max_seq_length", "lora_rank", "max_steps", "gradient_accumulation_steps", "save_steps", "seed"):
        if isinstance(config[key], bool) or not isinstance(config[key], int):
            raise LanguageRigError(f"{key} must be an integer.")
    if not 128 <= config["max_seq_length"] <= 8192 or not 1 <= config["lora_rank"] <= 256:
        raise LanguageRigError("Sequence length/rank outside supported bounds.")
    if any(config[k] < 1 for k in ("max_steps", "gradient_accumulation_steps", "save_steps")):
        raise LanguageRigError("Steps/accumulation must be positive.")
    for key in ("learning_rate", "epochs"):
        if isinstance(config[key], bool) or not isinstance(config[key], (int, float)) or not math.isfinite(config[key]) or config[key] <= 0:
            raise LanguageRigError(f"{key} must be positive and finite.")
    if config["learning_rate"] > 0.001:
        raise LanguageRigError("Learning rate exceeds the pilot limit.")
    if not isinstance(config["model_id"], str) or not config["model_id"].strip():
        raise LanguageRigError("Model ID is empty.")
    if not isinstance(config["model_revision"], str) or not config["model_revision"].strip():
        raise LanguageRigError("Model revision is empty.")
    manifest = verify_dataset(Path(config["dataset"]))
    config_hash = digest(json.dumps(config, sort_keys=True))
    return {"format": "languagerig-training-plan/v1", "status": "planned",
            "config": config, "config_sha256": config_hash,
            "dataset_sha256": manifest["dataset_sha256"], "mode": manifest["mode"],
            "counts": manifest["counts"],
            "dependencies": {name: importlib.util.find_spec(name) is not None
                             for name in ("torch", "transformers", "peft", "accelerate", "bitsandbytes", "datasets")},
            "gpu_policy": "one visible CUDA GPU; no implicit pooling of VRAM",
            "model_downloaded": False, "training_executed": False}


def encode_batch(batch: dict, tokenizer, mode: str, length: int) -> dict:
    """Preserve all raw text windows; SFT loss only on the final assistant turn."""
    result = {"input_ids": [], "attention_mask": [], "labels": []}
    if mode == "text":
        for text in batch["text"]:
            ids = list(tokenizer(text, add_special_tokens=False)["input_ids"])
            if tokenizer.eos_token_id is not None:
                ids.append(tokenizer.eos_token_id)
            for start in range(0, len(ids), length):
                window = ids[start:start + length]
                if len(window) < 2:
                    continue
                result["input_ids"].append(window)
                result["attention_mask"].append([1] * len(window))
                result["labels"].append(window.copy())
    else:
        for messages in batch["messages"]:
            prefix = list(tokenizer.apply_chat_template(messages[:-1], tokenize=True, add_generation_prompt=True))
            full = list(tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=False))
            if full[:len(prefix)] != prefix:
                raise LanguageRigError("Chat template cannot be safely masked for this model.")
            if len(full) > length:
                raise LanguageRigError("Instruction exceeds max_seq_length; shorten it or choose a larger window.")
            if len(full) <= len(prefix):
                raise LanguageRigError("Instruction has no assistant target tokens.")
            result["input_ids"].append(full)
            result["attention_mask"].append([1] * len(full))
            result["labels"].append([-100] * len(prefix) + full[len(prefix):])
    return result


def run_training(config_path: Path, *, execute=False, resume: Path | None = None) -> dict:
    plan = training_plan(config_path)
    if not execute:
        return plan
    missing = [name for name, available in plan["dependencies"].items() if not available]
    if missing:
        raise LanguageRigError("Install languagerig[train]; missing: " + ", ".join(missing))
    if int(os.getenv("WORLD_SIZE", "1")) != 1:
        raise LanguageRigError("This pilot runner supports one GPU/process; distributed training is not enabled.")
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["DO_NOT_TRACK"] = "1"
    import torch
    if not torch.cuda.is_available():
        raise LanguageRigError("Training requires CUDA; no weights were downloaded.")
    if torch.cuda.device_count() != 1:
        raise LanguageRigError("Select one GPU with CUDA_VISIBLE_DEVICES before training.")
    from datasets import load_dataset
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (AutoConfig, AutoModelForCausalLM, AutoTokenizer,
                              BitsAndBytesConfig, Trainer, TrainerCallback, TrainingArguments)
    config = plan["config"]
    output = Path(config["output_dir"])
    run_path = output / "run.json"
    if resume:
        if not run_path.is_file():
            raise LanguageRigError("Resume needs the original run.json.")
        previous = read_json(run_path)
        if previous.get("config_sha256") != plan["config_sha256"] or previous.get("dataset_sha256") != plan["dataset_sha256"]:
            raise LanguageRigError("Resume config/dataset differs from the original run.")
        resume = resume.resolve()
        if output.resolve() not in resume.parents or not (resume / "trainer_state.json").is_file():
            raise LanguageRigError("Resume must point to a checkpoint inside the original output directory.")
        revision = previous["resolved_revision"]
    else:
        if output.exists() and any(output.iterdir()):
            raise LanguageRigError("Run directory is not empty; choose a new output_dir or resume.")
        resolved = AutoConfig.from_pretrained(config["model_id"], revision=config["model_revision"], trust_remote_code=False)
        revision = getattr(resolved, "_commit_hash", None)
        if not revision:
            raise LanguageRigError("Cannot pin model revision; use a Hugging Face model repository.")
    output.mkdir(parents=True, exist_ok=True)
    run = {**plan, "format": "languagerig-run/v1", "status": "running",
           "resolved_revision": revision, "started_at": now(), "training_executed": True,
           "gpu": torch.cuda.get_device_name(0), "quality_improvement": "not_measured",
           "runtime_versions": {name: importlib.metadata.version(name) for name in
                                ("torch", "transformers", "peft", "accelerate", "bitsandbytes", "datasets")}}
    write_json(run_path, run)
    try:
        tokenizer = AutoTokenizer.from_pretrained(config["model_id"], revision=revision, trust_remote_code=False)
        if tokenizer.eos_token_id is None:
            raise LanguageRigError("Tokenizer needs an EOS token.")
        if tokenizer.pad_token_id is None:
            tokenizer.pad_token = tokenizer.eos_token
        tokenizer.padding_side = "right"
        if plan["mode"] == "instruction" and not tokenizer.chat_template:
            raise LanguageRigError("Instruction tuning requires the model's chat template.")
        model = AutoModelForCausalLM.from_pretrained(
            config["model_id"], revision=revision, trust_remote_code=False,
            quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                  bnb_4bit_use_double_quant=True,
                                                  bnb_4bit_compute_dtype=torch.float16),
            dtype=torch.float16, device_map={"": 0})
        model.config.use_cache = False
        model = prepare_model_for_kbit_training(model)
        model = get_peft_model(model, LoraConfig(
            r=config["lora_rank"], lora_alpha=config["lora_rank"] * 2,
            lora_dropout=0.05, target_modules="all-linear", task_type="CAUSAL_LM", bias="none"))
        # Test is deliberately absent: checkpoint selection only sees validation.
        dataset = load_dataset("json", data_files={
            name: str(Path(config["dataset"]) / f"{name}.jsonl") for name in ("train", "validation")},
            cache_dir=str(output / "dataset-cache"))
        tokenized = {}
        for name in ("train", "validation"):
            tokenized[name] = dataset[name].map(
                lambda batch: encode_batch(batch, tokenizer, plan["mode"], config["max_seq_length"]),
                batched=True, remove_columns=dataset[name].column_names, load_from_cache_file=False)
            if not len(tokenized[name]):
                raise LanguageRigError("No tokenized examples in " + name)
        run["tokenized_counts"] = {name: len(value) for name, value in tokenized.items()}
        write_json(run_path, run)
        def collate(features):
            max_length = max(len(feature["input_ids"]) for feature in features)
            return {key: torch.tensor([
                feature[key] + [padding] * (max_length - len(feature[key])) for feature in features])
                for key, padding in (("input_ids", tokenizer.pad_token_id), ("attention_mask", 0), ("labels", -100))}
        class Progress(TrainerCallback):
            def on_log(self, args, state, control, logs=None, **kwargs):
                event = {"at": now(), "step": state.global_step, **(logs or {})}
                with (output / "progress.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        arguments = TrainingArguments(
            output_dir=str(output), per_device_train_batch_size=1, per_device_eval_batch_size=1,
            gradient_accumulation_steps=config["gradient_accumulation_steps"],
            learning_rate=config["learning_rate"], num_train_epochs=config["epochs"],
            max_steps=config["max_steps"], fp16=True, gradient_checkpointing=True,
            gradient_checkpointing_kwargs={"use_reentrant": False},
            eval_strategy="steps", eval_steps=config["save_steps"], save_steps=config["save_steps"],
            save_total_limit=2, logging_steps=1, report_to=[], seed=config["seed"],
            optim="adamw_torch", dataloader_num_workers=0, label_names=["labels"])
        trainer = Trainer(model=model, args=arguments, processing_class=tokenizer,
                          train_dataset=tokenized["train"], eval_dataset=tokenized["validation"],
                          data_collator=collate, callbacks=[Progress()])
        trainer.train(resume_from_checkpoint=str(resume) if resume else None)
        metrics = trainer.evaluate()
        trainer.save_model(str(output / "adapter"))
        tokenizer.save_pretrained(output / "adapter")
        run.update(status="trained", completed_at=now(), validation_metrics=metrics,
                   adapter_dir=str(output / "adapter"))
        write_json(run_path, run)
        return run
    except BaseException as exc:
        run.update(status="failed", ended_at=now(), error_type=type(exc).__name__)
        write_json(run_path, run)
        raise
