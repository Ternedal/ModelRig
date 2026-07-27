package dk.ternedal.modelrig.logic

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
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

    // Designguiden afsnit 07 foreskriver tre statustekster. De hoerer til her og
    // ikke i UI'et, fordi valget mellem dem ER routing-beslutningen -- og fordi
    // en streng i en composable ikke kan testes.
    @Test
    fun `status foelger turens plan`() {
        fun status(mode: String, tools: Boolean, rag: Boolean) =
            TurnRouter.plan(TurnInput(mode, tools, rag, hasCloudKey = true, allowRagCloud = true)).let(TurnStatus::forPlan)

        assertEquals(TurnStatus.THINKING, status("rig", tools = false, rag = false))
        assertEquals(TurnStatus.RAG, status("rig", tools = false, rag = true))
        assertEquals(TurnStatus.TOOLS, status("rig", tools = true, rag = false))
        // Tools vinder over RAG: naar begge er til, er det vaerktoejet der koerer.
        assertEquals(TurnStatus.TOOLS, status("rig", tools = true, rag = true))
        // Cloud uden rig er ikke en videns-soegning, uanset ragMode-toggle.
        assertEquals(TurnStatus.THINKING, status("cloud", tools = false, rag = true))
    }

    @Test
    fun `status er aldrig tom`() {
        for (mode in listOf("rig", "cloud")) {
            for (tools in listOf(true, false)) {
                for (rag in listOf(true, false)) {
                    val p = TurnRouter.plan(TurnInput(mode, tools, rag, true, true))
                    assertTrue("tom status for $mode/$tools/$rag", TurnStatus.forPlan(p).isNotBlank())
                }
            }
        }
    }
}
