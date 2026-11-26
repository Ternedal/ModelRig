package dk.ternedal.modelrig.desktop

import dk.ternedal.modelrig.desktop.net.ChatResult
import kotlin.test.Test
import kotlin.test.assertEquals

/** #966: a Tools reply is the rig's, visibly, in the bubble as in the toolbar. */
class KalivToolsReplyPresentationTest {
    @Test
    fun toolsRepliesAreMarkedAsServedByTheRig() {
        assertEquals(ChatResult.Source.LOCAL, toolsReplySource())
    }
}
