package dk.ternedal.modelrig.voice

import java.util.concurrent.atomic.AtomicBoolean
import okhttp3.Call

/**
 * Cancellation owned by a single spoken turn, not by the shared chat stream.
 *
 * Coroutine cancellation alone does not interrupt a blocking OkHttp execute()
 * call. Registering the Call here makes Stop and microphone barge-in close the
 * HTTP stream as well as the local audio player. The lock covers the race where
 * Stop is pressed before the worker's HTTP Call is registered.
 */
class VoiceTurnCancellation {
    val stopFlag = AtomicBoolean(false)

    private val lock = Any()
    private var activeCall: Call? = null

    fun register(call: Call) {
        val alreadyStopped = synchronized(lock) {
            if (stopFlag.get()) {
                true
            } else {
                activeCall = call
                false
            }
        }
        if (alreadyStopped) call.cancel()
    }

    fun stop() {
        val toCancel = synchronized(lock) {
            stopFlag.set(true)
            activeCall.also { activeCall = null }
        }
        toCancel?.cancel()
    }

    /** Release the reference after completion without cancelling finished HTTP. */
    fun clear() {
        synchronized(lock) {
            activeCall = null
        }
    }
}
