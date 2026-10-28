package dk.ternedal.modelrig.net

import android.content.Context
import androidx.lifecycle.LifecycleOwner
import okhttp3.OkHttpClient

/** One VisionRig control step as the app sees it. */
data class VisionRigStep(
    /** VisionRig's desired-state: may this source capture right now? */
    val desiredEnabled: Boolean,
    /** The camera is open. */
    val captureActive: Boolean,
    /** A frame was sent in this step. */
    val frameSent: Boolean,
)

/**
 * The phone camera as a VisionRig sensor source (`kaliv-android`).
 *
 * Implemented over VisionRig's own producer (desired-state, heartbeat,
 * SensorPacket, shared cadence runner). Capture opens only while VisionRig's
 * desired-state enables the source. [run] blocks between suspensions and must
 * run off the main thread; cancellation closes capture.
 */
interface VisionRigCameraProducer : AutoCloseable {
    suspend fun run(onStep: (VisionRigStep) -> Unit)
}

/**
 * Builds a producer for one paired gateway. [http] is [VisionRigHttp.client]:
 * the implementation must route every gateway request through it.
 */
fun interface VisionRigCameraProducerFactory {
    fun create(
        context: Context,
        lifecycleOwner: LifecycleOwner,
        connection: VisionRigConnection,
        http: OkHttpClient,
    ): VisionRigCameraProducer
}
