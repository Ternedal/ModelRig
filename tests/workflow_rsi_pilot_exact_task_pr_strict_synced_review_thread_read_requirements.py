from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
SUPPORT=ROOT/"tests"/"support"
if str(SUPPORT) not in sys.path:sys.path.insert(0,str(SUPPORT))
from rsi_pilot_exact_task_pr_strict_synced_review_thread_read_requirements_contract import run_contract
if __name__=="__main__":run_contract()
