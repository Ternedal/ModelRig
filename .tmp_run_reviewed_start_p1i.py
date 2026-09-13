from pathlib import Path

source_path = Path(".tmp_fix_reviewed_start_p1i.py")
source = source_path.read_text(encoding="utf-8")

call = '''replace_once(\n    "worker/app/agent3/planner.py",\n    \'\'\'                return _recover_materialized_reviewed_start(\\n                    plan_id,\\n                    reserved_run_id,\\n                    envelope,\\n                    review_reads=review_reads,\\n                )\\n\'\'\',\n    \'\'\'                return _recover_materialized_reviewed_start(\\n                    plan_id,\\n                    reserved_run_id,\\n                    envelope,\\n                    review_reads=review_reads,\\n                    reviewed_template=template,\\n                )\\n\'\'\',\n)\n'''

if source.count(call) != 2:
    raise SystemExit(f"expected two mirrored recovery-call patch blocks, found {source.count(call)}")

replacement = '''p = Path("worker/app/agent3/planner.py")\ntext = p.read_text(encoding="utf-8")\nold = \'\'\'                return _recover_materialized_reviewed_start(\\n                    plan_id,\\n                    reserved_run_id,\\n                    envelope,\\n                    review_reads=review_reads,\\n                )\\n\'\'\'\nnew = \'\'\'                return _recover_materialized_reviewed_start(\\n                    plan_id,\\n                    reserved_run_id,\\n                    envelope,\\n                    review_reads=review_reads,\\n                    reviewed_template=template,\\n                )\\n\'\'\'\ncount = text.count(old)\nif count != 2:\n    raise SystemExit(f"worker/app/agent3/planner.py: expected two mirrored recovery calls, found {count}")\np.write_text(text.replace(old, new, 2), encoding="utf-8")\n'''

first = source.find(call)
source = source[:first] + replacement + source[first + len(call):]
second = source.find(call, first + len(replacement))
if second < 0:
    raise SystemExit("second mirrored patch block disappeared unexpectedly")
source = source[:second] + source[second + len(call):]

runtime = Path("/tmp/modelrig_p1i_runtime.py")
runtime.write_text(source, encoding="utf-8")
exec(compile(source, str(runtime), "exec"), {"__name__": "__main__"})
