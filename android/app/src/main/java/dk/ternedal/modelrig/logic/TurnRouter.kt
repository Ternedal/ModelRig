package dk.ternedal.modelrig.logic

/**
 * The ONE place a turn's route is decided.
 *
 * The main send path and the retry path used to compute these flags
 * independently, and they diverged: the retry handler had no tools branch at
 * all, so a retried action turn silently became plain chat (audit 1.58.35
 * P1-1). Duplicated predicates cannot be kept in sync by discipline -- both
 * paths now call this router, so a divergence is structurally impossible, and
 * the decision table is unit-tested on the JVM (the client's first tested
 * logic; see TurnRouterTest).
 *
 * The flags reproduce the historical semantics EXACTLY -- this is a pure
 * extraction, not a redesign (the #2a state-machine redesign is separate,
 * device-verified work):
 *  - useTools: Tools on, and either rig mode or cloud mode with a key (tools
 *    live behind the rig's gate; cloud+tools routes through the rig).
 *  - useRag:   rig mode with document knowledge on. (RAG-in-cloud outside the
 *    tools path is #2a territory and deliberately NOT routed here.)
 *  - useCloud: cloud mode -- kept independent of the tools decision because
 *    branch ORDER (tools first) is what makes tools win, matching the
 *    original code.
 *  - toolsWithRag: the tools turn may also search documents; in cloud mode
 *    only when the user explicitly allowed RAG-to-cloud.
 */
data class TurnInput(
    val mode: String, // "rig" | "cloud"
    val toolsMode: Boolean,
    val ragMode: Boolean,
    val hasCloudKey: Boolean,
    val allowRagCloud: Boolean,
)

data class TurnPlan(
    val useTools: Boolean,
    val useRag: Boolean,
    val useCloud: Boolean,
    val toolsWithRag: Boolean,
)

object TurnRouter {
    fun plan(i: TurnInput): TurnPlan {
        val useTools = i.toolsMode && (i.mode == "rig" || (i.mode == "cloud" && i.hasCloudKey))
        return TurnPlan(
            useTools = useTools,
            useRag = i.mode == "rig" && i.ragMode,
            useCloud = i.mode == "cloud",
            toolsWithRag = useTools && i.ragMode && (i.mode == "rig" || i.allowRagCloud),
        )
    }
}
