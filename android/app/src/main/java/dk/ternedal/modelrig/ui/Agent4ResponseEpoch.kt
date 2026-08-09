package dk.ternedal.modelrig.ui

/** Exact credential identity used by one Agent 4 read request. */
internal data class Agent4ConnectionIdentity(
    val baseUrl: String,
    val token: String,
)

/**
 * Invalidates asynchronous Agent 4 responses after refresh or credential drift.
 *
 * The guard owns no network, cache or privileged payload. A new initial load
 * advances the epoch. Paging work captures the current ticket and may mutate UI
 * state only while both epoch and exact credential identity still match.
 */
internal class Agent4ResponseEpoch {
    internal data class Ticket(
        val epoch: Long,
        val connection: Agent4ConnectionIdentity,
    )

    private var epoch: Long = 0

    fun invalidate() {
        epoch += 1
    }

    fun begin(connection: Agent4ConnectionIdentity): Ticket {
        invalidate()
        return Ticket(epoch, connection)
    }

    fun capture(connection: Agent4ConnectionIdentity): Ticket = Ticket(epoch, connection)

    fun accepts(
        ticket: Ticket,
        currentConnection: Agent4ConnectionIdentity?,
    ): Boolean = ticket.epoch == epoch && ticket.connection == currentConnection
}
