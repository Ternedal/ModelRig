"""Profile-driven generation job runner (ModelRig #2296).

Ported from image_job_runner.py on feat/image-generation-contract-20261021,
re-cut at the ownership seam: the runner hands bytes to an ArtifactSink and
does not know the media store. It picks the adapter by the job's profile id
and checks the request against that profile before any rendering.

No model weights are downloaded and no inference is activated on import.
"""
from __future__ import annotations

import json
from typing import Mapping

from .image_job_store import ImageJobStore
from .media_generation_contract import (
    ArtifactSink,
    ArtifactSinkUnavailable,
    GenerationError,
    GenerationRequest,
    GeneratorAdapter,
    JobKeyedArtifactSink,
    RenderedArtifact,
)
from .media_generation_profiles import ModelProfile, validate_request

FAILED = "image_generation_failed"
REJECTED = "image_request_rejected"
PROFILE_UNAVAILABLE = "image_profile_unavailable"

_REQUEST_PARAMS = ("width", "height", "steps", "seed", "input_asset_id", "frames")


class GenerationJobRunner:
    def __init__(self, jobs: ImageJobStore, sink: ArtifactSink,
                 profiles: Mapping[str, ModelProfile], adapters: Mapping[str, GeneratorAdapter]):
        if not isinstance(sink, ArtifactSink):
            raise TypeError("sink must implement ArtifactSink")
        if set(adapters) - set(profiles):
            raise ValueError("an adapter has no enabled profile")
        self.jobs = jobs
        self.sink = sink
        self.profiles = dict(profiles)
        self.adapters = dict(adapters)

    def _request(self, job: dict) -> GenerationRequest:
        try:
            params = json.loads(job["params"])
        except (TypeError, ValueError):
            raise GenerationError("stored parameters are unreadable") from None
        if not isinstance(params, dict) or set(params) - set(_REQUEST_PARAMS) - {"task"}:
            raise GenerationError("unknown job parameters")
        profile = self.profiles[job["profile_id"]]
        task = params.get("task", next(iter(sorted(profile.tasks))))
        request = GenerationRequest(
            profile_id=job["profile_id"], task=task, prompt=job["prompt"],
            **{key: params[key] for key in _REQUEST_PARAMS if key in params},
        )
        return validate_request(profile, request)

    def run_one(self) -> dict | None:
        job = self.jobs.claim()
        if job is None:
            return None
        job_id = job["id"]
        adapter = self.adapters.get(job["profile_id"])
        if adapter is None or job["profile_id"] not in self.profiles:
            # The profile is not enabled on this executor: refuse, do not guess.
            self.jobs.finish(job_id, error=PROFILE_UNAVAILABLE)
            return {"job_id": job_id, "state": "failed", "error": PROFILE_UNAVAILABLE}
        try:
            request = self._request(job)
        except GenerationError:
            self.jobs.finish(job_id, error=REJECTED)
            return {"job_id": job_id, "state": "failed", "error": REJECTED}
        try:
            rendered = adapter.render(request)
            if not isinstance(rendered, RenderedArtifact):
                raise TypeError("adapter must return RenderedArtifact")
            if rendered.mime_type not in self.profiles[job["profile_id"]].outputs:
                raise GenerationError("adapter produced a type its profile does not declare")
            if isinstance(self.sink, JobKeyedArtifactSink):  # deterministic id: reconcilable after a crash
                asset_id = self.sink.publish_and_register_for_job(job_id, rendered.data, rendered.extension)
            else:
                asset_id = self.sink.publish(rendered.data, rendered.extension)
            if not isinstance(asset_id, str) or not asset_id:
                raise ArtifactSinkUnavailable("sink returned no asset id")
        except ArtifactSinkUnavailable:
            # A missing external disk is a fatal safety event. Do not touch the
            # job (recover_interrupted() fails it at the next start) and do not
            # fall back to another disk.
            raise
        except Exception:
            # Never persist model exceptions: they can contain prompts or paths.
            self.jobs.finish(job_id, error=FAILED)
            return {"job_id": job_id, "state": "failed", "error": FAILED}
        # The artifact is durable now. A completion write that fails must not turn into an
        # ordinary failure (#2318 6517442207): leave the job running for reconciliation.
        try:
            recorded = self.jobs.finish(job_id, asset_id=asset_id)
        except Exception:
            recorded = False
        if not recorded:
            return {"job_id": job_id, "state": "unrecorded", "asset_id": asset_id}
        return {"job_id": job_id, "state": "completed", "asset_id": asset_id}
