package dk.ternedal.modelrig.ui.agent

import dk.ternedal.modelrig.net.Agent3Client

/**
 * Det ENESTE sted i chatfladen der må starte en agent-kørsel.
 *
 * Hvorfor et helt objekt til tre linjer: min første udgave lod kortet kalde
 * startPlan direkte og stolede på et politik-tjek lige ovenfor. Da jeg
 * saboterede tjekket, opdagede gaten det ikke — den kunne kun se at filen
 * NÆVNTE politikken, ikke at kaldet var beskyttet. En regel man kan fjerne
 * uden at noget bliver rødt, er ikke en regel.
 *
 * Nu er starten flyttet herind, og gaten kræver at startPlan KUN findes i
 * denne fil, og at denne fil spørger politikken. Fjerner man tjekket, er der
 * ingen politik tilbage i filen → rød. Kalder man udenom, er startPlan i en
 * forkert fil → rød.
 */
object AgentStartGuard {

    /**
     * Starter planen, hvis og kun hvis politikken tillader det.
     * Returnerer null ved afvisning — fladen viser da vejen til
     * agent-skærmen frem for at prøve alligevel.
     */
    fun start(
        client: Agent3Client,
        source: AgentStartPolicy.Source,
        message: String,
        steps: List<Agent3Client.Step>,
        planId: String?,
    ): Agent3Client.Run? {
        val verdict = AgentStartPolicy.verdictForPlan(source, message, steps)
        if (verdict !is AgentStartPolicy.Verdict.Start) return null
        val id = planId?.takeIf { it.isNotBlank() } ?: return null
        return client.startPlan(id)
    }
}
