#!/usr/bin/env python3
from pathlib import Path

path = Path("scripts/candidate_freeze_check.py")
text = path.read_text(encoding="utf-8")
old = '''from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
'''
new = '''from __future__ import annotations

# Candidate inspection must not create the bytecode that its own freeze gate
# correctly forbids. Set both interpreter and child-process contracts before
# importing the worker fingerprint module or invoking version_tool.
import os
import sys
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import tempfile
'''
if text.count(old) != 1:
    raise SystemExit("candidate freeze import block did not match exactly once")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
