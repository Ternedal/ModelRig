# Consciousness Core C12 — Sleep / Dormancy

C12 introduces a sleep-like lifecycle for clean close/shutdown without pretending
that cognition continues while the host is off.

Clean close:
AWAKE -> PREPARING_SLEEP -> persisted SleepRecord -> process off.

While actually off:
- no ThoughtEngine;
- no workspace/attention loop;
- no BodyRig/VoiceRig action;
- no Memory 4 write;
- no scheduler created by C12;
- cognition_continues=false.

Wake:
new runtime epoch + C11 Temporal Sense -> WakeReceipt -> WAKING -> later AWAKE.

A WakeReceipt preserves the same self_id and Person Revision, calculates grounded
offline duration when possible, restores only references to open goals/loops, and
has no execution/scheduler/memory-write authority.

If no clean SleepRecord exists, startup may classify the gap as
UNPLANNED_DORMANCY rather than fabricating normal sleep.

A future dream-like mode, if wanted, must be real powered computation while idle
and separately gated. It is not part of powered-off sleep.

production_activation=false.
