package dk.ternedal.modelrig.ui.agent

import android.content.Context

/**
 * Hvilken agent-kørsel hører til hvilken samtale.
 *
 * ADR-A3-001's operationelle valg: en kørsel startet i én samtale vises KUN
 * dér. Uden den binding ville en kørsel dukke op i alle samtaler — også dem
 * den intet har med at gøre — og kørsler startet på agent-skærmen ville
 * blande sig i chatten.
 *
 * Bindingen er LOKAL. Riggen ved intet om samtaler, så det er telefonens
 * eget regnskab; forsvinder det, forsvinder kun visningen — aldrig kørslen.
 */
class AgentRunBinding(context: Context) {

    private val prefs = context.getSharedPreferences("kaliv_agent_runs", Context.MODE_PRIVATE)

    fun runFor(conversationId: String?): String? =
        conversationId?.takeIf { it.isNotBlank() }?.let { prefs.getString(key(it), null) }

    fun bind(conversationId: String?, runId: String) {
        val c = conversationId?.takeIf { it.isNotBlank() } ?: return
        prefs.edit().putString(key(c), runId).apply()
    }

    /** Kaldes når kørslen er slut — bindingen skal ikke overleve den. */
    fun clear(conversationId: String?) {
        val c = conversationId?.takeIf { it.isNotBlank() } ?: return
        prefs.edit().remove(key(c)).apply()
    }

    private fun key(conversationId: String) = "run:$conversationId"
}
