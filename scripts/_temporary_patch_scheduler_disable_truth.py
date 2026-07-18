from pathlib import Path

runner_path = Path("worker/app/schedule_runner.py")
text = runner_path.read_text(encoding="utf-8")
old = '''        except Exception as exc:
            warning = self._bounded(
                f"{detail}; efterregistrering fejlede ({type(exc).__name__}); "
                "planen er slået fra for at undgå en ekstra kørsel"
            )
            try:
                self.schedules.set_enabled(schedule.schedule_id, False, now=now)
            except Exception:
                # The schedule store is already failing. The claimed occurrence
                # was consumed before execution, and a later tick will meet the
                # same store boundary rather than retrying inside this call.
                pass
            try:
                self.jobs.update(job_id, status="completed", detail=warning)
            except Exception:
                # Do not let a second bookkeeping store rewrite execution truth.
                pass
            return "completed"
'''
new = '''        except Exception as exc:
            disabled = False
            try:
                disabled = self.schedules.set_enabled(
                    schedule.schedule_id,
                    False,
                    now=now,
                ) is True
            except Exception:
                # The schedule store is already failing. The claimed occurrence
                # was consumed before execution, and a later tick will meet the
                # same store boundary rather than retrying inside this call.
                pass

            recovery = (
                "planen er slået fra for at undgå en ekstra kørsel"
                if disabled
                else "planen kunne ikke slås fra; kontrollér den før næste kørsel"
            )
            warning = self._bounded(
                f"{detail}; efterregistrering fejlede ({type(exc).__name__}); "
                f"{recovery}"
            )
            try:
                self.jobs.update(job_id, status="completed", detail=warning)
            except Exception:
                # Do not let a second bookkeeping store rewrite execution truth.
                pass
            return "completed"
'''
if text.count(old) != 1:
    raise SystemExit(f"expected disable block exactly once, found {text.count(old)}")
runner_path.write_text(text.replace(old, new), encoding="utf-8")


test_path = Path("tests/worker_schedule_post_execution.py")
test = test_path.read_text(encoding="utf-8")
old_init = '''class FailingScheduleAccounting:
    def __init__(self, schedule: Schedule, *, fail_record: bool) -> None:
        self.schedule = schedule
        self.fail_record = fail_record
        self.recorded: list[bool] = []
        self.disabled: list[tuple[str, bool, float]] = []
'''
new_init = '''class FailingScheduleAccounting:
    def __init__(
        self,
        schedule: Schedule,
        *,
        fail_record: bool,
        disable_result: bool = True,
    ) -> None:
        self.schedule = schedule
        self.fail_record = fail_record
        self.disable_result = disable_result
        self.recorded: list[bool] = []
        self.disabled: list[tuple[str, bool, float]] = []
'''
old_set = '''    def set_enabled(self, schedule_id: str, enabled: bool, *, now: float):
        self.disabled.append((schedule_id, enabled, now))
        return True
'''
new_set = '''    def set_enabled(self, schedule_id: str, enabled: bool, *, now: float):
        self.disabled.append((schedule_id, enabled, now))
        return self.disable_result
'''
old_make = '''def make_case(*, fail_record: bool, fail_completed: bool = False):
'''
new_make = '''def make_case(
    *,
    fail_record: bool,
    fail_completed: bool = False,
    disable_result: bool = True,
):
'''
old_ctor = '''    schedules = FailingScheduleAccounting(schedule, fail_record=fail_record)
'''
new_ctor = '''    schedules = FailingScheduleAccounting(
        schedule,
        fail_record=fail_record,
        disable_result=disable_result,
    )
'''
anchor = '''check(
    "schedule database unavailable" not in jobs.updates[-1].get("detail", ""),
    "internal database error text is not exposed",
)


# If the schedule budget is durable but JobStore is down, execution truth is
'''
insert = '''check(
    "schedule database unavailable" not in jobs.updates[-1].get("detail", ""),
    "internal database error text is not exposed",
)


# A failed disable write must not produce the false claim that the plan is off.
runner, claim, schedules, jobs, gate = make_case(
    fail_record=True,
    disable_result=False,
)
outcome = runner._run_claim(claim, "job-1", NOW)
detail = jobs.updates[-1].get("detail", "")
check(outcome == "completed", "failed disable still preserves execution truth")
check("planen kunne ikke slås fra" in detail, "the warning admits disable was not confirmed")
check("planen er slået fra" not in detail, "the warning never invents a successful disable")
check(schedules.recorded == [True], "failed disable does not rewrite the run as failed")


# If the schedule budget is durable but JobStore is down, execution truth is
'''
replacements = [
    (old_init, new_init, "fake schedule init"),
    (old_set, new_set, "fake set_enabled"),
    (old_make, new_make, "make_case signature"),
    (old_ctor, new_ctor, "fake schedule construction"),
    (anchor, insert, "disable failure regression"),
]
for old_part, new_part, name in replacements:
    if test.count(old_part) != 1:
        raise SystemExit(f"expected {name} exactly once, found {test.count(old_part)}")
    test = test.replace(old_part, new_part)
test_path.write_text(test, encoding="utf-8")
