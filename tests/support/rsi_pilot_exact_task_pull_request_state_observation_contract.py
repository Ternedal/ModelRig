"""Adversarial contract for ADR-DC-056 exact GitHub PR-state observation."""
from __future__ import annotations

import inspect
import json
import os
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control.github_read import HttpResponse  # noqa: E402
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_pull_request_mutation_authorization as auth,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_pull_request_mutation_requirements as pr_requirements,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_pull_request_state_observation as observation,
)
from rsi_pilot_exact_task_pull_request_mutation_authorization_contract import (  # noqa: E402
    _claim,
    _human_authority,
    _material,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-pull-request-state-observation-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (
        observation.PilotExactTaskPullRequestStateObservationError,
        ValueError,
        TypeError,
        AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-056 unexpectedly accepted unsafe PR state")


class _Transport:
    def __init__(
        self,
        requirements,
        *,
        head_sha: str | None = None,
        pulls: object | None = None,
        head_status: int = 200,
        pulls_status: int = 200,
        head_content_type: str = "application/vnd.github+json",
        pulls_content_type: str = "application/vnd.github+json",
        pulls_link: str | None = None,
        redirect: bool = False,
    ) -> None:
        self.requirements = requirements
        self.head_sha = head_sha or requirements.predicted_commit_sha
        self.pulls = [] if pulls is None else pulls
        self.head_status = head_status
        self.pulls_status = pulls_status
        self.head_content_type = head_content_type
        self.pulls_content_type = pulls_content_type
        self.pulls_link = pulls_link
        self.redirect = redirect
        self.calls: list[tuple[str, dict[str, str], int, int]] = []

    def get(
        self,
        url: str,
        *,
        headers,
        timeout_seconds: int,
        max_bytes: int,
    ) -> HttpResponse:
        captured = dict(headers)
        self.calls.append((url, captured, timeout_seconds, max_bytes))
        assert "Authorization" not in captured
        assert "authorization" not in captured
        assert "Cookie" not in captured
        assert "cookie" not in captured
        assert captured["X-GitHub-Api-Version"] == "2022-11-28"
        if "/git/ref/heads/" in url:
            body = json.dumps(
                {
                    "ref": self.requirements.head_ref,
                    "object": {
                        "type": "commit",
                        "sha": self.head_sha,
                    },
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            response_headers = {
                "content-type": self.head_content_type,
                "etag": '"head-etag"',
            }
            if self.redirect:
                response_headers["location"] = "https://evil.invalid/"
            return HttpResponse(
                status=self.head_status,
                headers=response_headers,
                body=body,
            )
        if "/pulls?" in url:
            body = json.dumps(
                self.pulls,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            response_headers = {
                "content-type": self.pulls_content_type,
                "etag": '"pulls-etag"',
            }
            if self.pulls_link is not None:
                response_headers["link"] = self.pulls_link
            if self.redirect:
                response_headers["location"] = "https://evil.invalid/"
            return HttpResponse(
                status=self.pulls_status,
                headers=response_headers,
                body=body,
            )
        raise AssertionError(f"unexpected URL: {url}")


def _proof(requirements):
    claim = _claim(requirements)
    verifier, signature = _human_authority(claim)
    supplied = auth._verify_pilot_exact_task_pull_request_mutation_authorization(
        pull_request_mutation_requirements=requirements,
        authorization=claim,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-15T06:24:00Z",
    )
    fresh = auth._verify_pilot_exact_task_pull_request_mutation_authorization(
        pull_request_mutation_requirements=requirements,
        authorization=claim,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-15T06:24:10Z",
    )
    observation.require_fresh_pull_request_mutation_authorization_proof_identity(
        supplied,
        fresh,
    )
    return claim, verifier, signature, supplied, fresh


def run_contract() -> None:
    if os.name == "nt":
        return

    material = _material()
    requirements = material[-1]
    source_material = material[0]
    try:
        _claim_value, _verifier, _signature, supplied, fresh = _proof(requirements)
        transport = _Transport(requirements)
        times = iter(("2026-09-15T06:24:20Z", "2026-09-15T06:24:30Z"))
        result = observation._observe_verified_pilot_exact_task_pull_request_state(
            authorization_proof=supplied,
            fresh_authorization_proof=fresh,
            transport=transport,
            now_provider=lambda: next(times),
        )

        assert len(transport.calls) == 2
        head_url = urllib.parse.urlsplit(transport.calls[0][0])
        pulls_url = urllib.parse.urlsplit(transport.calls[1][0])
        assert head_url.scheme == "https"
        assert head_url.netloc == "api.github.com"
        assert head_url.path == (
            "/repos/Ternedal/ModelRig/git/ref/heads/" + requirements.head_branch
        )
        assert head_url.query == ""
        assert pulls_url.scheme == "https"
        assert pulls_url.netloc == "api.github.com"
        assert pulls_url.path == "/repos/Ternedal/ModelRig/pulls"
        assert urllib.parse.parse_qs(pulls_url.query, strict_parsing=True) == {
            "state": ["open"],
            "head": [f"Ternedal:{requirements.head_branch}"],
            "base": ["main"],
            "per_page": ["2"],
            "page": ["1"],
        }
        assert transport.calls[0][2:] == (30, 32 * 1024)
        assert transport.calls[1][2:] == (30, 128 * 1024)

        assert result.pull_request_mutation_authorization_proof_sha256 == supplied.sha256
        assert result.pull_request_mutation_requirements_sha256 == requirements.sha256
        assert (
            result.remote_publication_write_transaction_sha256
            == requirements.remote_publication_write_transaction_sha256
        )
        assert result.remote_publication_nonce_sha256 == requirements.remote_publication_nonce_sha256
        assert result.pr_mutation_nonce_sha256 == supplied.pr_mutation_nonce_sha256
        assert result.predicted_commit_sha == requirements.predicted_commit_sha
        assert result.repository == "Ternedal/ModelRig"
        assert result.api_host == "api.github.com"
        assert result.api_version == "2022-11-28"
        assert result.base_ref == "main"
        assert result.head_owner == "Ternedal"
        assert result.head_ref == requirements.head_ref
        assert result.head_branch == requirements.head_branch
        assert result.observed_at_utc == "2026-09-15T06:24:30Z"
        assert result.head_response_bytes > 0
        assert result.pull_list_response_bytes == 2
        assert result.observation_authenticated is True

        for field in (
            "human_pr_mutation_authorization_verified",
            "fresh_authorization_proof_reverified",
            "live_pr_requirements_verified",
            "remote_head_ref_observed",
            "remote_head_sha_matches_exact_candidate",
            "pull_request_state_observed",
            "existing_open_pull_request_absent",
            "same_repository_head_verified",
            "exact_base_ref_verified",
            "fixed_api_host_verified",
            "https_only_read",
            "get_only_read",
            "redirects_forbidden",
            "credentials_not_required",
            "response_bounded",
            "one_shot_pr_mutation_reservation_required",
            "host_pinned_pr_credential_capability_required",
            "merge_separately_authorized_required",
        ):
            assert getattr(result, field) is True
        for field in (
            "pr_mutation_authorization_consumed",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "pull_request_create_authorized",
            "pull_request_update_authorized",
            "ready_for_review_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert getattr(result, field) is False

        serialized = result.to_dict()
        reloaded = observation.PilotExactTaskPullRequestStateObservation.from_mapping(
            serialized
        )
        assert reloaded == result
        assert reloaded.sha256 == result.sha256
        assert reloaded.observation_authenticated is False

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(serialized)
        assert set(schema["required"]) == set(serialized)
        assert schema["properties"]["existing_open_pull_request_absent"]["const"] is True
        assert schema["properties"]["credentials_not_required"]["const"] is True
        assert schema["properties"]["pr_mutation_authorized"]["const"] is False
        assert schema["properties"]["pull_request_create_authorized"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        # A structurally valid but reloaded proof cannot recover live DC-054 provenance.
        reloaded_proof = auth.PilotExactTaskPullRequestMutationAuthorizationProof.from_mapping(
            supplied.to_dict()
        )
        assert (
            reloaded_proof.authorization.pull_request_mutation_requirements.requirements_authenticated
            is False
        )
        _reject(lambda: observation._require_live_proof(reloaded_proof))

        # The exact remote head must still equal the published candidate.
        drifted = _Transport(requirements, head_sha="f" * 40)
        _reject(
            lambda: observation._observe_verified_pilot_exact_task_pull_request_state(
                authorization_proof=supplied,
                fresh_authorization_proof=fresh,
                transport=drifted,
                now_provider=iter(("2026-09-15T06:24:20Z", "2026-09-15T06:24:30Z")).__next__,
            )
        )

        # Any matching open PR makes create-only PR state unavailable.
        existing = _Transport(
            requirements,
            pulls=[
                {
                    "number": 999,
                    "state": "open",
                    "base": {"ref": "main"},
                    "head": {
                        "ref": requirements.head_branch,
                        "sha": requirements.predicted_commit_sha,
                    },
                }
            ],
        )
        _reject(
            lambda: observation._observe_verified_pilot_exact_task_pull_request_state(
                authorization_proof=supplied,
                fresh_authorization_proof=fresh,
                transport=existing,
                now_provider=iter(("2026-09-15T06:24:20Z", "2026-09-15T06:24:30Z")).__next__,
            )
        )

        # Hidden pagination cannot be treated as proof of absence.
        paginated = _Transport(
            requirements,
            pulls=[],
            pulls_link=(
                '<https://api.github.com/repositories/1287914122/pulls?page=2>; rel="next"'
            ),
        )
        _reject(
            lambda: observation._observe_verified_pilot_exact_task_pull_request_state(
                authorization_proof=supplied,
                fresh_authorization_proof=fresh,
                transport=paginated,
                now_provider=iter(("2026-09-15T06:24:20Z", "2026-09-15T06:24:30Z")).__next__,
            )
        )

        redirected = _Transport(requirements, redirect=True)
        _reject(
            lambda: observation._observe_verified_pilot_exact_task_pull_request_state(
                authorization_proof=supplied,
                fresh_authorization_proof=fresh,
                transport=redirected,
                now_provider=iter(("2026-09-15T06:24:20Z", "2026-09-15T06:24:30Z")).__next__,
            )
        )

        wrong_content_type = _Transport(
            requirements,
            pulls_content_type="text/html",
        )
        _reject(
            lambda: observation._observe_verified_pilot_exact_task_pull_request_state(
                authorization_proof=supplied,
                fresh_authorization_proof=fresh,
                transport=wrong_content_type,
                now_provider=iter(("2026-09-15T06:24:20Z", "2026-09-15T06:24:30Z")).__next__,
            )
        )

        # A proof older than the DC-056 freshness ceiling fails closed even if
        # its original human authorization window has not yet expired.
        _reject(
            lambda: observation._observe_verified_pilot_exact_task_pull_request_state(
                authorization_proof=supplied,
                fresh_authorization_proof=fresh,
                transport=_Transport(requirements),
                now_provider=iter(("2026-09-15T06:29:11Z", "2026-09-15T06:29:12Z")).__next__,
            )
        )

        changed = dict(serialized)
        changed["pr_mutation_authorized"] = True
        _reject(
            lambda: observation.PilotExactTaskPullRequestStateObservation.from_mapping(
                changed
            )
        )
        changed = dict(serialized)
        changed["pull_request_create_authorized"] = True
        _reject(
            lambda: observation.PilotExactTaskPullRequestStateObservation.from_mapping(
                changed
            )
        )

        public_parameters = inspect.signature(
            observation.observe_pilot_exact_task_pull_request_state
        ).parameters
        assert tuple(public_parameters) == (
            "authorization_proof",
            "authorization_signature",
        )

        source = inspect.getsource(observation)
        for forbidden in (
            "create_pull_request",
            "update_pull_request",
            "merge_pull_request",
            'method="POST"',
            'method="PATCH"',
            'method="PUT"',
            'method="DELETE"',
        ):
            assert forbidden not in source
        assert '"Authorization"' not in inspect.getsource(observation._headers)
    finally:
        material[2].cleanup()
        material[1].cleanup()
        source_material[6].cleanup()
        source_material[5].cleanup()
        source_material[4].cleanup()
        source_material[3].cleanup()
        source_material[2].cleanup()
        source_material[1].cleanup()
        source_material[0].cleanup()


if __name__ == "__main__":
    run_contract()
