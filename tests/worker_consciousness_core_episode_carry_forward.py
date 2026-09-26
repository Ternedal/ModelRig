"""Contract checks for C31-E episode carry-forward policy."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"worker"))

from app.consciousness_core.episode_carry_forward import EpisodeCarryForwardError, plan_episode_carry_forward
from app.consciousness_core.episode_closure_evidence import EpisodeClosureEvidence, EpisodeKindCount, episode_closure_evidence_ref
from app.consciousness_core.episode_experience_review import TrustedEpisodeExperienceReview


SELF="self-"+"1"*32
PERSON="person-r0042"


def evidence(count=2):
    return EpisodeClosureEvidence(
        schema="kaliv-consciousness-core/episode-closure-evidence/v1",
        evidence_id="ecev-"+"2"*32,
        closed_episode_ref="episode:closed",
        boundary_signal_ref="boundary:1",
        self_id=SELF,
        person_revision=PERSON,
        open_reason="FIRST_MOMENT",
        close_reason="EXPLICIT",
        opened_anchor_id="tanch-"+"3"*32,
        closed_anchor_id="tanch-"+"4"*32,
        opened_sequence=1,
        closed_sequence=2,
        objective_elapsed_ms=100,
        total_moment_count=count,
        evicted_moment_count=0,
        retained_moment_count=count,
        retained_kind_counts=[] if count==0 else [EpisodeKindCount(kind="PERCEPTION",count=count)],
        salient_source_refs=[] if count==0 else ["source:episode"],
        participant_refs=[],
        active_goal_refs=[],
        max_retained_salience=0.0 if count==0 else 0.8,
        memory_review_disposition="NO_MOMENTS" if count==0 else "REFERENCE_EVIDENCE_ONLY",
        raw_text_included=False,
        raw_chain_of_thought_included=False,
        closed_episode_contents_retained=False,
        experience_candidate_created=False,
        durable_memory_write_authority=False,
        self_state_store_write_applied=False,
        model_calls=0,
        execution_authority=False,
        scheduling_authority=False,
        timer_authority=False,
        production_activation=False,
    )


def review(ev, decision):
    return TrustedEpisodeExperienceReview(
        schema="kaliv-consciousness-core/trusted-episode-experience-review/v1",
        review_id="erev-"+"5"*32,
        closure_evidence_ref=episode_closure_evidence_ref(ev),
        decision=decision,
        authority="trusted_semantic_review",
        reviewer_source_ref="reviewer:test",
        reviewed_candidate_ref="experience-candidate:approved" if decision=="APPROVE" else None,
        raw_text_asserted_from_closure_evidence=False,
        completed_turn_authority_asserted=False,
        production_activation=False,
    )


def test_closure_reference_can_reenter_bounded_attention_without_memory_write():
    ev=evidence()
    plan=plan_episode_carry_forward(ev)
    assert plan.disposition=="ADMIT_REFERENCE"
    assert plan.candidate is not None
    assert plan.candidate.source_ref==episode_closure_evidence_ref(ev)
    assert plan.memory4_called is False
    assert plan.durable_memory_write_authority is False
    assert plan.episode_contents_persisted is False
    assert plan.automatic_goal_resume is False


def test_approved_review_carries_only_explicit_review_and_candidate_refs():
    ev=evidence()
    plan=plan_episode_carry_forward(ev,review=review(ev,"APPROVE"))
    assert plan.disposition=="ADMIT_REFERENCE"
    assert plan.review_ref is not None
    assert plan.durable_memory_candidate_ref=="experience-candidate:approved"
    assert plan.candidate.source_ref==plan.review_ref
    assert plan.raw_text_included is False
    assert plan.raw_chain_of_thought_included is False


def test_rejected_review_is_not_carried_forward():
    ev=evidence()
    plan=plan_episode_carry_forward(ev,review=review(ev,"REJECT"))
    assert plan.disposition=="OMIT"
    assert plan.candidate is None
    assert plan.durable_memory_candidate_ref is None


def test_empty_episode_is_not_carried_forward():
    plan=plan_episode_carry_forward(evidence(0))
    assert plan.disposition=="OMIT"
    assert plan.candidate is None


def test_cross_evidence_review_fails_closed():
    ev=evidence()
    forged=review(ev,"APPROVE").model_copy(update={"closure_evidence_ref":"episode-closure-evidence:other"})
    try:
        plan_episode_carry_forward(ev,review=forged)
    except EpisodeCarryForwardError:
        pass
    else:
        raise AssertionError("cross-evidence review must fail closed")
