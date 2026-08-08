from pathlib import Path

path = Path('.github/workflows/_tests.yml')
text = path.read_text(encoding='utf-8')
old = '''          assert importlib.util.find_spec(
              "kaliv_dev_control._compatibility_v1.publisher_authorization"
          ) is None
'''
new = '''          try:
              compatibility_spec = importlib.util.find_spec(
                  "kaliv_dev_control._compatibility_v1.publisher_authorization"
              )
          except ModuleNotFoundError:
              compatibility_spec = None
          assert compatibility_spec is None
'''
if text.count(old) != 1:
    raise SystemExit(f'compatibility absence marker count was {text.count(old)}, expected 1')
path.write_text(text.replace(old, new), encoding='utf-8')
