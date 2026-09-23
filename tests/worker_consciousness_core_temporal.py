#!/usr/bin/env python3
from __future__ import annotations
import inspect,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"worker"))
from app.consciousness_core import ClockSample,TemporalContractError,TemporalState,anchor_from_clock,build_temporal_state,deadline_state,relate_anchors,temporal_experience_state
SELF="self-"+"1"*32; PERSON="person-r0007"; EA="epoch-"+"a"*32; EB="epoch-"+"b"*32
class TemporalTests(unittest.TestCase):
 def s(self,x,wall,mono,seq,epoch=EA,hour=10):
  return ClockSample(schema="kaliv-consciousness-core/clock-sample/v1",sample_id="clock-"+x*32,wall_time_unix_ms=wall,timezone_name="Europe/Copenhagen",utc_offset_minutes=120,local_hour=hour,monotonic_ms=mono,runtime_epoch_id=epoch,sampled_sequence=seq,source_ref="trusted:"+x,confidence=1.0,production_activation=False)
 def test_monotonic_beats_wall_jump(self):
  a=self.s("1",1000,100,1); b=self.s("2",900,600,2); r=relate_anchors(anchor_from_clock(a,event_ref="a"),anchor_from_clock(b,event_ref="b")); self.assertEqual((r.clock_basis,r.elapsed_ms),("monotonic",500))
  st=build_temporal_state(self_id=SELF,person_revision=PERSON,current_sample=b,session_started_anchor=anchor_from_clock(a,event_ref="start"),previous_sample=a); self.assertEqual(st.clock_anomaly,"wall_clock_backward")
 def test_restart_gap_not_identity_change(self):
  a=self.s("1",1000,9000,1,EA); b=self.s("2",31000,100,2,EB); st=build_temporal_state(self_id=SELF,person_revision=PERSON,current_sample=b,session_started_anchor=anchor_from_clock(b,event_ref="start"),previous_sample=a); self.assertEqual(st.self_id,SELF); self.assertTrue(st.continuity_gap_detected); self.assertEqual(st.continuity_gap_ms,30000)
 def test_stale_rejected(self):
  a=self.s("1",1000,100,2); b=self.s("2",2000,200,2)
  with self.assertRaises(TemporalContractError): build_temporal_state(self_id=SELF,person_revision=PERSON,current_sample=b,session_started_anchor=anchor_from_clock(a,event_ref="start"),previous_sample=a)
 def test_deadline_has_no_scheduler_authority(self):
  a=self.s("1",1000,100,1); b=self.s("2",61000,60100,2); d=deadline_state(now_anchor=anchor_from_clock(a,event_ref="now"),deadline_anchor=anchor_from_clock(b,event_ref="deadline")); self.assertEqual(d.orientation,"FUTURE"); self.assertFalse(d.scheduling_authority); self.assertFalse(d.execution_authority)
 def test_duration_salience_keeps_objective_time(self):
  dense=temporal_experience_state(observation_window_ms=60000,event_count=20,attention_load=.9); sparse=temporal_experience_state(observation_window_ms=60000,event_count=0,attention_load=.1); self.assertEqual(dense.objective_elapsed_ms,sparse.objective_elapsed_ms); self.assertEqual(dense.duration_salience,"expanded"); self.assertEqual(sparse.duration_salience,"compressed")
 def test_no_model_clock_or_scheduler_authority(self):
  for f in ("model","provider","cognitive_profile"): self.assertNotIn(f,TemporalState.model_fields)
  self.assertNotIn("model",inspect.signature(build_temporal_state).parameters)
  src=(ROOT/"worker/app/consciousness_core/temporal.py").read_text()
  for forbidden in ("datetime.now(","time.time(","time.monotonic(","schedule_service","from app.tools"): self.assertNotIn(forbidden,src)
if __name__=="__main__": unittest.main(verbosity=2)
