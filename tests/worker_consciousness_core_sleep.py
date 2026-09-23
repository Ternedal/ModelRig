#!/usr/bin/env python3
from __future__ import annotations
import sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"worker"))
from app.consciousness_core import ClockSample,anchor_from_clock,prepare_sleep,wake_from_sleep,SleepContractError
SELF="self-"+"1"*32; PERSON="person-r0007"; EA="epoch-"+"a"*32; EB="epoch-"+"b"*32
def sample(x,wall,mono,seq,epoch):
 return ClockSample(schema="kaliv-consciousness-core/clock-sample/v1",sample_id="clock-"+x*32,wall_time_unix_ms=wall,timezone_name="Europe/Copenhagen",utc_offset_minutes=120,local_hour=10,monotonic_ms=mono,runtime_epoch_id=epoch,sampled_sequence=seq,source_ref="trusted:"+x,confidence=1.0,production_activation=False)
class SleepTests(unittest.TestCase):
 def test_clean_sleep_wake_preserves_identity_and_has_no_offline_cognition(self):
  a=anchor_from_clock(sample("1",1000,9000,1,EA),event_ref="sleep")
  s=prepare_sleep(self_id=SELF,person_revision=PERSON,entry_anchor=a,reason="app_closed",open_goal_refs=["goal:1"],open_loop_refs=["loop:1"])
  b=anchor_from_clock(sample("2",61000,100,2,EB),event_ref="wake")
  w=wake_from_sleep(wake_anchor=b,sleep_record=s,expected_self_id=SELF,expected_person_revision=PERSON)
  self.assertEqual((w.self_id,w.person_revision),(SELF,PERSON)); self.assertEqual(w.dormancy_kind,"PLANNED_SLEEP"); self.assertEqual(w.offline_duration_ms,60000); self.assertFalse(w.cognition_during_gap); self.assertEqual(w.resume_goal_refs,["goal:1"]); self.assertFalse(w.execution_authority)
 def test_unplanned_dormancy_is_distinct_from_sleep(self):
  a=anchor_from_clock(sample("1",1000,9000,1,EA),event_ref="last-running")
  b=anchor_from_clock(sample("2",11000,100,2,EB),event_ref="wake")
  w=wake_from_sleep(wake_anchor=b,last_known_anchor=a,expected_self_id=SELF,expected_person_revision=PERSON)
  self.assertEqual(w.dormancy_kind,"UNPLANNED_DORMANCY"); self.assertIsNone(w.sleep_id); self.assertFalse(w.cognition_during_gap)
 def test_forged_identity_fails_closed(self):
  a=anchor_from_clock(sample("1",1000,9000,1,EA),event_ref="sleep")
  s=prepare_sleep(self_id=SELF,person_revision=PERSON,entry_anchor=a,reason="host_shutdown")
  b=anchor_from_clock(sample("2",11000,100,2,EB),event_ref="wake")
  with self.assertRaises(SleepContractError): wake_from_sleep(wake_anchor=b,sleep_record=s,expected_self_id="self-"+"2"*32,expected_person_revision=PERSON)
 def test_clock_rollback_makes_duration_unknown_not_invented(self):
  a=anchor_from_clock(sample("1",10000,9000,1,EA),event_ref="sleep")
  s=prepare_sleep(self_id=SELF,person_revision=PERSON,entry_anchor=a,reason="app_closed")
  b=anchor_from_clock(sample("2",9000,100,2,EB),event_ref="wake")
  w=wake_from_sleep(wake_anchor=b,sleep_record=s)
  self.assertFalse(w.duration_known); self.assertIsNone(w.offline_duration_ms)
 def test_sleep_record_never_grants_runtime_authority(self):
  a=anchor_from_clock(sample("1",1000,9000,1,EA),event_ref="sleep")
  s=prepare_sleep(self_id=SELF,person_revision=PERSON,entry_anchor=a,reason="suspend",pending_review_refs=["ccand:1"])
  self.assertFalse(s.cognition_continues); self.assertFalse(s.execution_authority); self.assertFalse(s.scheduling_authority); self.assertFalse(s.durable_memory_write_authority)
 def test_no_background_compute_or_scheduler_import(self):
  src=(ROOT/"worker/app/consciousness_core/sleep.py").read_text()
  for forbidden in ("asyncio.create_task","schedule_service","Agent3Orchestrator","MemoryStore","time.sleep(","threading.Thread","ThoughtEngine"):
   self.assertNotIn(forbidden,src)
if __name__=="__main__": unittest.main(verbosity=2)
