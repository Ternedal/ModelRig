from pathlib import Path

path = Path('.github/dc-l13-workflow-projection.py')
text = path.read_text(encoding='utf-8')
old = '''replace_once(
    workflow,
    ''' + "'''" + '''          for future_module in (
              "kaliv_dev_control.local_candidate_materialization",
              "kaliv_dev_control.local_candidate_materialization_h5c",
          ):
              assert importlib.util.find_spec(future_module) is None, future_module
''' + "'''" + ''',
    ''' + "'''" + '''          for landed_module in (
              "kaliv_dev_control.local_candidate_materialization",
              "kaliv_dev_control.local_candidate_materialization_h5c",
          ):
              assert importlib.util.find_spec(landed_module) is not None, landed_module
''' + "'''" + ''',
)
'''
new = '''future_marker = ''' + "'''" + '''          for future_module in (
              "kaliv_dev_control.local_candidate_materialization",
              "kaliv_dev_control.local_candidate_materialization_h5c",
          ):
              assert importlib.util.find_spec(future_module) is None, future_module
''' + "'''" + '''
landed_marker = ''' + "'''" + '''          for landed_module in (
              "kaliv_dev_control.local_candidate_materialization",
              "kaliv_dev_control.local_candidate_materialization_h5c",
          ):
              assert importlib.util.find_spec(landed_module) is not None, landed_module
''' + "'''" + '''
workflow_text = workflow.read_text(encoding="utf-8")
count = workflow_text.count(future_marker)
if count != 4:
    raise SystemExit(f"{workflow}: future marker count {count}, expected 4")
workflow.write_text(workflow_text.replace(future_marker, landed_marker), encoding="utf-8")
'''
if text.count(old) != 1:
    raise SystemExit('projector replacement marker mismatch')
path.write_text(text.replace(old, new), encoding='utf-8')
