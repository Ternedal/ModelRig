"""Local approval issuance gate; no HTTP endpoint or production policy binding.

Caller identity and administrator privileges MUST be established outside this
module. Task ACLs alone are not proof of trusted actor authentication.
"""
from continuum_state import State
from task_access import TaskAccess
from task_store import TaskStore
from approval_store import ApprovalStore

class ApprovalGate:
    def __init__(self, database):
        self.store = TaskStore(database)
        self.access = TaskAccess(database)
        self.approvals = ApprovalStore(database)

    def issue_for_checkpoint(self, *, task_id, approver_id, executor_id,
                             capability, expected_revision, ttl_seconds=300):
        """Require explicit approve ACL and exact awaiting-approval revision.

        Approval tokens remain scoped to executor_id, not approver_id.
        This gate is a local prototype, NOT a trusted remote authorization API.
        """
        if not all(isinstance(x, str) and x.strip()
                   for x in (task_id, approver_id, executor_id, capability)):
            raise ValueError("missing approval scope")
        self.access.require(task_id, approver_id, "approve")
        task = self.store.get(task_id)
        if (task.state != State.AWAITING_APPROVAL or
                task.revision != expected_revision or
                type(expected_revision) is not int):
            raise PermissionError("checkpoint mismatch")
        return self.approvals.issue(
            task_id=task_id, actor_id=executor_id, capability=capability,
            revision=expected_revision, ttl_seconds=ttl_seconds)
