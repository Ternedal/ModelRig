package dk.ternedal.modelrig.logic

import okhttp3.Call

/**
 * Local-first chat with the opt-in automatic cloud fallback (`auto_cloud_fallback`, default off).
 *
 * A request the user STOPPED is never sent to the cloud. Before this policy, Stop
 * (`activeCall?.cancel()`) made the rig call throw `IOException("Canceled")`, and the
 * pre-output catch treated that like "rig down" and answered via Ollama Cloud.
 *
 * What reaches the cloud is unchanged: [dk.ternedal.modelrig.net.CloudClient] still sends
 * only the current user message (D5, `CloudCurrentMessageOnlyTest`). This policy only
 * decides WHETHER the fallback runs.
 */
object CloudFallbackPolicy {

    /**
     * The fallback may run only when all of these hold:
     * - the rig emitted nothing (a mid-stream failure is surfaced, never answered twice);
     * - the user did not stop the request;
     * - a cloud key exists;
     * - the user opted in.
     */
    fun shouldFallback(emitted: Int, rigCallCancelled: Boolean, hasCloudKey: Boolean, optedIn: Boolean): Boolean =
        emitted == 0 && !rigCallCancelled && hasCloudKey && optedIn

    /**
     * Runs [rig] and, if it fails before emitting anything, [cloud], under [shouldFallback].
     * Returns true when the cloud answered.
     *
     * [register] is the screen's Stop hook (it records the call that Stop cancels). Each
     * route gets a wrapped hook:
     * - The rig's hook remembers the rig call. A failure is then judged cancelled when
     *   that call was cancelled.
     * - The cloud's hook re-checks the rig call right after registering the cloud call.
     *   Stop pressed after the rig failed but before the cloud call existed lands on the
     *   rig call. The check then cancels the cloud call before `execute()` sends anything.
     *
     * Any failure that may not fall back is rethrown unchanged.
     */
    fun runLocalFirst(
        hasCloudKey: Boolean,
        optedIn: Boolean,
        register: (Call) -> Unit,
        rig: (register: (Call) -> Unit, onEmit: () -> Unit) -> Unit,
        cloud: (register: (Call) -> Unit) -> Unit,
    ): Boolean {
        var emitted = 0
        var rigCall: Call? = null
        try {
            rig({ call -> rigCall = call; register(call) }, { emitted++ })
            return false
        } catch (e: Exception) {
            // kotlinx.coroutines.CancellationException is this JVM type: a cancelled
            // coroutine is a stop too.
            val cancelled = e is java.util.concurrent.CancellationException || rigCall?.isCanceled() == true
            if (!shouldFallback(emitted, cancelled, hasCloudKey, optedIn)) throw e
        }
        cloud { call ->
            register(call)
            if (rigCall?.isCanceled() == true) call.cancel()
        }
        return true
    }
}
