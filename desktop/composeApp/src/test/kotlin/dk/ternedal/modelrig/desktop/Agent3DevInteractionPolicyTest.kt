package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class Agent3DevInteractionPolicyTest {
    @Test fun idleSurfaceMayPreview() = assertTrue(
        Agent3DevInteractionPolicy.canPreview("status", false, null)
    )

    @Test fun blankOrBusyPreviewFailsClosed() {
        assertFalse(Agent3DevInteractionPolicy.canPreview("   ", false, null))
        assertFalse(Agent3DevInteractionPolicy.canPreview("status", true, null))
    }

    @Test fun activeWaitingAndUnknownRunsRetainAuthority() {
        assertFalse(Agent3DevInteractionPolicy.canPreview("status", false, "running"))
        assertFalse(Agent3DevInteractionPolicy.canPreview("status", false, "waiting_confirmation"))
        assertFalse(Agent3DevInteractionPolicy.canPreview("status", false, "future_state"))
    }

    @Test fun terminalRunWithExecutingToolCannotBeReplaced() = assertFalse(
        Agent3DevInteractionPolicy.canPreview(
            "status", false, "cancelled", "executing", "unavailable"
        )
    )

    @Test fun terminalRunWithPendingToolRequestCannotBeReplaced() = assertFalse(
        Agent3DevInteractionPolicy.canPreview(
            "status", false, "cancelled", "completed_after_cancel", "pending"
        )
    )

    @Test fun fullyTerminalRunMayBeReplaced() {
        assertTrue(Agent3DevInteractionPolicy.canPreview("ny opgave", false, "completed"))
        assertTrue(
            Agent3DevInteractionPolicy.canPreview(
                "ny opgave", false, "cancelled", "completed_after_cancel", "terminal"
            )
        )
    }

    @Test fun startRequiresUsablePreviewAndNoRun() {
        assertTrue(Agent3DevInteractionPolicy.canStart("plan-1", 1, null, false, false))
        assertTrue(Agent3DevInteractionPolicy.canStart("plan-1", 1, true, false, false))
        assertFalse(Agent3DevInteractionPolicy.canStart("plan-1", 1, false, false, false))
        assertFalse(Agent3DevInteractionPolicy.canStart("plan-1", 1, true, false, true))
    }

    @Test fun startRejectsBusyMissingOrEmptyPreview() {
        assertFalse(Agent3DevInteractionPolicy.canStart("plan-1", 1, true, true, false))
        assertFalse(Agent3DevInteractionPolicy.canStart(null, 1, true, false, false))
        assertFalse(Agent3DevInteractionPolicy.canStart("", 1, true, false, false))
        assertFalse(Agent3DevInteractionPolicy.canStart("plan-1", 0, true, false, false))
    }
}
