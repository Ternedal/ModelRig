"""Model profiles: fail-closed validation, safe defaults and request limits (ModelRig #2296).

The profiles here are synthetic test fixtures. Their revisions are made-up
40-hex strings, not real model commits; no profile ships with ModelRig.
"""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

from app.media_generation_contract import GenerationError, GenerationRequest, RenderedArtifact
from app.media_generation_profiles import (
    enabled_profiles,
    load_profile_dir,
    parse_profile,
    validate_request,
)

FAKE_REV = "0123456789abcdef0123456789abcdef01234567"


def image_profile(**overrides):
    profile = {
        "schema": "kaliv-media-profile/v1",
        "profile_id": "sdxl-base",
        "modality": "image",
        "tasks": ["text_to_image"],
        "backend": "diffusers",
        "pipeline": "StableDiffusionXLPipeline",
        "model_id": "example/sdxl-base",
        "revision": FAKE_REV,
        "limits": {"max_prompt_chars": 500, "sizes": [[1024, 1024], [832, 1216]], "max_steps": 40, "max_frames": None},
        "outputs": ["image/png"],
        "resources": {"min_usable_gib": 8, "reserve_gib": 2, "devices": ["cuda:1"], "cpu_offload": False},
        "qualification": "candidate",
        "license": "openrail++",
        "backend_options": {},
    }
    profile.update(overrides)
    return profile


def video_profile(**overrides):
    profile = image_profile(
        profile_id="wan-t2v", modality="video", tasks=["text_to_video", "image_to_video"],
        backend="comfyui", pipeline=None, model_id="example/wan", outputs=["video/mp4"],
        limits={"max_prompt_chars": 500, "sizes": [[832, 480]], "max_steps": 30, "max_frames": 81},
        license="apache-2.0",
        backend_options={"template_name": "wan-t2v.json", "template_sha256": "ab" * 32, "fps": 16,
                         "max_render_seconds": 1800, "max_output_bytes": 512 * 1024 * 1024, "port": 8188},
    )
    profile.update(overrides)
    return profile


class ProfileParsingTests(unittest.TestCase):
    def test_valid_image_and_video_profiles(self):
        image = parse_profile(image_profile())
        self.assertEqual(image.pipeline, "StableDiffusionXLPipeline")
        self.assertEqual(image.limits.sizes[0], (1024, 1024))
        self.assertEqual(image.resources.min_usable_gib, 8.0)
        video = parse_profile(video_profile())
        self.assertEqual(video.limits.max_frames, 81)
        self.assertIsNone(video.pipeline)

    def test_unknown_or_missing_keys_are_refused(self):
        extra = image_profile(unexpected=True)
        missing = image_profile()
        del missing["license"]
        nested = image_profile()
        nested["resources"] = dict(nested["resources"], gpu_hint="fast")
        for bad in (extra, missing, nested):
            with self.subTest(bad=sorted(set(bad) ^ set(image_profile()))), self.assertRaises(GenerationError):
                parse_profile(bad)

    def test_unknown_backend_pipeline_task_mime_and_mismatches(self):
        cases = {
            "backend": image_profile(backend="tensorrt"),
            "pipeline not allowlisted": image_profile(pipeline="DiffusionPipeline"),
            "arbitrary class path": image_profile(pipeline="os.system"),
            "pipeline on comfyui": video_profile(pipeline="FluxPipeline"),
            "task": image_profile(tasks=["text_to_3d"]),
            "video task on image": image_profile(tasks=["text_to_video"]),
            "mime": image_profile(outputs=["image/webp"]),
            "video mime on image": image_profile(outputs=["video/mp4"]),
            "diffusers for video": video_profile(backend="diffusers", pipeline="FluxPipeline"),
            "schema": image_profile(schema="kaliv-media-profile/v2"),
            "modality": image_profile(modality="audio"),
            "qualification": image_profile(qualification="production"),
        }
        for name, bad in cases.items():
            with self.subTest(case=name), self.assertRaises(GenerationError):
                parse_profile(bad)

    def test_backend_options_are_exact_per_backend(self):
        video = parse_profile(video_profile())
        self.assertEqual(video.backend_options.template_name, "wan-t2v.json")
        self.assertEqual(video.backend_options.fps, 16)
        self.assertIsNone(parse_profile(image_profile()).backend_options)
        good = video_profile()["backend_options"]
        bad_options = [
            {"template_name": "../wan.json"}, {"template_name": "dir/wan.json"}, {"template_name": "wan.yaml"},
            {"template_name": "Wan.json"}, {"template_name": "..json"}, {"template_sha256": "ab" * 31},
            {"template_sha256": "AB" * 32}, {"template_sha256": None}, {"fps": 0}, {"fps": 61},
            {"fps": True}, {"max_render_seconds": 5}, {"max_render_seconds": 7201},
            {"max_output_bytes": 2 * 1024 ** 3 + 1}, {"max_output_bytes": 10}, {"port": 80},
            {"port": 65536}, {"port": "8188"},
        ]
        for patch in bad_options:
            with self.subTest(options=patch), self.assertRaises(GenerationError):
                parse_profile(video_profile(backend_options=dict(good, **patch)))
        extra = dict(good, listen="0.0.0.0")
        missing = {k: v for k, v in good.items() if k != "port"}
        for options in (extra, missing, {}, None, []):
            with self.subTest(options=options), self.assertRaises(GenerationError):
                parse_profile(video_profile(backend_options=options))
        for options in (good, {"fps": 16}, None):
            with self.subTest(diffusers_options=options), self.assertRaises(GenerationError):
                parse_profile(image_profile(backend_options=options))

    def test_revision_must_be_pinned(self):
        for revision in ("", "main", "v1.0", FAKE_REV[:39], FAKE_REV.upper(), None, 123):
            with self.subTest(revision=revision), self.assertRaises(GenerationError):
                parse_profile(image_profile(revision=revision))

    def test_model_id_cannot_be_a_url_or_escape(self):
        for model_id in ("https://evil.example/model", "../../etc", "a/../../b", "", " spaced", "x" * 201):
            with self.subTest(model_id=model_id), self.assertRaises(GenerationError):
                parse_profile(image_profile(model_id=model_id))

    def test_limits_and_resources_are_strict(self):
        bad_limits = [
            {"max_prompt_chars": 0}, {"max_prompt_chars": True}, {"max_steps": 201}, {"max_steps": 1.5},
            {"sizes": []}, {"sizes": [[1001, 1024]]}, {"sizes": [[32, 32]]}, {"sizes": [[1024]]},
            {"sizes": [[1024, 1024], [1024, 1024]]}, {"max_frames": 10},
        ]
        for patch in bad_limits:
            profile = image_profile()
            profile["limits"] = dict(profile["limits"], **patch)
            with self.subTest(limits=patch), self.assertRaises(GenerationError):
                parse_profile(profile)
        video = video_profile()
        video["limits"] = dict(video["limits"], max_frames=None)
        with self.assertRaises(GenerationError):
            parse_profile(video)
        bad_resources = [
            {"min_usable_gib": 0}, {"min_usable_gib": float("nan")}, {"min_usable_gib": True},
            {"reserve_gib": -1}, {"reserve_gib": float("inf")}, {"devices": []}, {"devices": ["cpu"]},
            {"devices": ["cuda:16"]}, {"devices": ["cuda:1", "cuda:1"]}, {"cpu_offload": "yes"},
        ]
        for patch in bad_resources:
            profile = image_profile()
            profile["resources"] = dict(profile["resources"], **patch)
            with self.subTest(resources=patch), self.assertRaises(GenerationError):
                parse_profile(profile)


class ProfileDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def write(self, name, obj):
        (self.dir / name).write_text(json.dumps(obj), encoding="utf-8")

    def test_loads_every_json_profile(self):
        self.write("sdxl.json", image_profile())
        self.write("flux.json", image_profile(profile_id="flux-dev", pipeline="FluxPipeline", license="flux-1-dev-non-commercial"))
        (self.dir / "README.txt").write_text("ignored")
        self.assertEqual(sorted(load_profile_dir(str(self.dir))), ["flux-dev", "sdxl-base"])

    def test_one_invalid_file_fails_the_whole_set(self):
        self.write("good.json", image_profile())
        self.write("bad.json", image_profile(profile_id="other", pipeline="DiffusionPipeline"))
        with self.assertRaises(GenerationError) as caught:
            load_profile_dir(str(self.dir))
        self.assertIn("bad.json", str(caught.exception))

    def test_duplicates_bad_json_and_unsafe_paths_are_refused(self):
        self.write("a.json", image_profile())
        self.write("b.json", image_profile())
        with self.assertRaises(GenerationError):
            load_profile_dir(str(self.dir))
        (self.dir / "b.json").write_text("{not json")
        with self.assertRaises(GenerationError):
            load_profile_dir(str(self.dir))
        with self.assertRaises(GenerationError):
            load_profile_dir("relative/profiles")
        link = Path(self.tmp.name + "-link")
        link.symlink_to(self.dir, target_is_directory=True)
        self.addCleanup(link.unlink)
        with self.assertRaises(GenerationError):
            load_profile_dir(str(link))


class EnabledProfileTests(unittest.TestCase):
    def setUp(self):
        self.profiles = {
            "sdxl-base": parse_profile(image_profile()),
            "qwen-image": parse_profile(image_profile(profile_id="qwen-image", pipeline="QwenImagePipeline",
                                                      qualification="rig-qualified", license="apache-2.0")),
        }

    def test_nothing_is_enabled_by_default(self):
        self.assertEqual(enabled_profiles(self.profiles, env={}), {})
        self.assertEqual(enabled_profiles(self.profiles, env={"KALIV_MEDIA_PROFILES_ENABLED": "  "}), {})

    def test_rig_qualified_profile_can_be_enabled(self):
        self.assertEqual(list(enabled_profiles(self.profiles, env={"KALIV_MEDIA_PROFILES_ENABLED": "qwen-image"})),
                         ["qwen-image"])

    def test_candidate_needs_the_explicit_opt_in(self):
        env = {"KALIV_MEDIA_PROFILES_ENABLED": "sdxl-base"}
        with self.assertRaises(GenerationError):
            enabled_profiles(self.profiles, env=env)
        with self.assertRaises(GenerationError):
            enabled_profiles(self.profiles, env=dict(env, KALIV_MEDIA_ALLOW_CANDIDATE_PROFILES="true"))
        self.assertEqual(list(enabled_profiles(self.profiles, env=dict(env, KALIV_MEDIA_ALLOW_CANDIDATE_PROFILES="1"))),
                         ["sdxl-base"])

    def test_unknown_or_malformed_lists_are_refused(self):
        for raw in ("flux-dev", "qwen-image,", "qwen-image,qwen-image", ",qwen-image"):
            with self.subTest(raw=raw), self.assertRaises(GenerationError):
                enabled_profiles(self.profiles, env={"KALIV_MEDIA_PROFILES_ENABLED": raw})

    def test_reads_the_real_environment_when_none_is_given(self):
        old = os.environ.pop("KALIV_MEDIA_PROFILES_ENABLED", None)
        self.addCleanup(lambda: old is not None and os.environ.__setitem__("KALIV_MEDIA_PROFILES_ENABLED", old))
        self.assertEqual(enabled_profiles(self.profiles), {})


class RequestValidationTests(unittest.TestCase):
    def setUp(self):
        self.image = parse_profile(image_profile())
        self.video = parse_profile(video_profile())

    def req(self, **kw):
        base = {"profile_id": "sdxl-base", "task": "text_to_image", "prompt": "a lighthouse"}
        base.update(kw)
        return GenerationRequest(**base)

    def test_defaults_are_filled_from_the_profile(self):
        request = validate_request(self.image, self.req())
        self.assertEqual((request.width, request.height, request.steps, request.frames), (1024, 1024, 30, None))
        video = validate_request(self.video, GenerationRequest(profile_id="wan-t2v", task="text_to_video", prompt="waves"))
        self.assertEqual((video.width, video.height, video.frames, video.steps), (832, 480, 81, 30))

    def test_requests_outside_the_profile_are_refused_before_any_gpu_work(self):
        bad = [
            self.req(profile_id="flux-dev"), self.req(task="image_to_image"), self.req(prompt=" "),
            self.req(prompt="x" * 501), self.req(width=1024), self.req(width=512, height=512),
            self.req(width=1024.0, height=1024), self.req(steps=41), self.req(steps=0), self.req(steps=True),
            self.req(seed=-1), self.req(seed=2**32), self.req(seed=1.0), self.req(frames=10),
            self.req(input_asset_id="img_1"), self.req(extra={"cfg": 7}),
        ]
        for request in bad:
            with self.subTest(request=request), self.assertRaises(GenerationError):
                validate_request(self.image, request)
        with self.assertRaises(GenerationError):
            validate_request(self.image, "not a request")

    def test_video_frames_and_input_asset_rules(self):
        ok = GenerationRequest(profile_id="wan-t2v", task="image_to_video", prompt="pan left",
                               input_asset_id="img_123", frames=49)
        self.assertEqual(validate_request(self.video, ok).frames, 49)
        for bad in (
            GenerationRequest(profile_id="wan-t2v", task="image_to_video", prompt="pan"),
            GenerationRequest(profile_id="wan-t2v", task="image_to_video", prompt="pan", input_asset_id="../x"),
            GenerationRequest(profile_id="wan-t2v", task="image_to_video", prompt="pan", input_asset_id=123),
            GenerationRequest(profile_id="wan-t2v", task="text_to_video", prompt="pan", frames=82),
        ):
            with self.subTest(bad=bad), self.assertRaises(GenerationError):
                validate_request(self.video, bad)

    def test_rendered_artifact_types_are_closed(self):
        self.assertEqual(RenderedArtifact(b"\x89PNG", "image/png").extension, ".png")
        for data, mime in ((b"", "image/png"), (bytearray(b"x"), "image/png"), (b"x", "image/webp"), ("x", "image/png")):
            with self.subTest(mime=mime), self.assertRaises(GenerationError):
                RenderedArtifact(data, mime)


if __name__ == "__main__":
    unittest.main()
