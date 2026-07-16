package dk.ternedal.modelrig.logic

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * The route decision as a table. Every row is (input -> expected flags); the
 * named rows at the bottom pin the exact situations that were bugs before the
 * extraction, so a regression fails with a story, not just a boolean.
 */
class TurnRouterTest {

    private data class Row(
        val name: String,
        val mode: String,
        val tools: Boolean,
        val rag: Boolean,
        val key: Boolean,
        val allowRagCloud: Boolean,
        val expect: TurnPlan,
    )

    private val table = listOf(
        Row("rig plain", "rig", false, false, false, false,
            TurnPlan(useTools = false, useRag = false, useCloud = false, toolsWithRag = false, useRagCloud = false)),
        Row("rig rag", "rig", false, true, false, false,
            TurnPlan(useTools = false, useRag = true, useCloud = false, toolsWithRag = false, useRagCloud = false)),
        Row("rig tools", "rig", true, false, false, false,
            TurnPlan(useTools = true, useRag = false, useCloud = false, toolsWithRag = false, useRagCloud = false)),
        Row("rig tools+rag", "rig", true, true, false, false,
            TurnPlan(useTools = true, useRag = true, useCloud = false, toolsWithRag = true, useRagCloud = false)),
        Row("cloud plain", "cloud", false, false, true, false,
            TurnPlan(useTools = false, useRag = false, useCloud = true, toolsWithRag = false, useRagCloud = false)),
        Row("cloud tools (key)", "cloud", true, false, true, false,
            TurnPlan(useTools = true, useRag = false, useCloud = true, toolsWithRag = false, useRagCloud = false)),
        Row("cloud tools+rag, rag-to-cloud NOT allowed", "cloud", true, true, true, false,
            TurnPlan(useTools = true, useRag = false, useCloud = true, toolsWithRag = false, useRagCloud = false)),
        Row("cloud tools+rag, rag-to-cloud allowed", "cloud", true, true, true, true,
            TurnPlan(useTools = true, useRag = false, useCloud = true, toolsWithRag = true, useRagCloud = false)),
        // Historical bug pins:
        Row("cloud tools WITHOUT key -> plain cloud (tools can't run; key gates the rig route)",
            "cloud", true, false, false, false,
            TurnPlan(useTools = false, useRag = false, useCloud = true, toolsWithRag = false, useRagCloud = false)),
        // The pre-2a pin ("RAG never silently routes to cloud") is SUPERSEDED by
        // design: with the persisted consent given, cloud+rag now plans the
        // rig-mediated useRagCloud route (dormant until trin 3-4 wire it).
        Row("cloud rag WITH consent -> useRagCloud (2a trin 2; dormant)",
            "cloud", false, true, true, true,
            TurnPlan(useTools = false, useRag = false, useCloud = true, toolsWithRag = false, useRagCloud = true)),
        Row("cloud rag WITHOUT consent -> plain cloud, never silent RAG egress (INV-06)",
            "cloud", false, true, true, false,
            TurnPlan(useTools = false, useRag = false, useCloud = true, toolsWithRag = false, useRagCloud = false)),
        Row("cloud rag with consent but NO key -> no rig-mediated route (key gates it, like tools)",
            "cloud", false, true, false, true,
            TurnPlan(useTools = false, useRag = false, useCloud = true, toolsWithRag = false, useRagCloud = false)),
    )

    @Test
    fun decisionTable() {
        for (r in table) {
            val got = TurnRouter.plan(TurnInput(r.mode, r.tools, r.rag, r.key, r.allowRagCloud))
            assertEquals("row: ${r.name}", r.expect, got)
        }
    }

    @Test
    fun toolsAlwaysWinBranchOrder() {
        // useCloud stays true in cloud mode even when tools win -- branch ORDER
        // (tools checked first) is the mechanism, exactly as in AppUi. If
        // someone "simplifies" useCloud to exclude tools, this documents why not.
        val p = TurnRouter.plan(TurnInput("cloud", toolsMode = true, ragMode = false, hasCloudKey = true, allowRagCloud = false))
        assertEquals(true, p.useTools)
        assertEquals(true, p.useCloud)
    }
}
