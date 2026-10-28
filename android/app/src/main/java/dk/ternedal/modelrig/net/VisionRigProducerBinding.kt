package dk.ternedal.modelrig.net

import android.content.Context
import androidx.lifecycle.LifecycleOwner
import dk.kaliv.visionrig.android.CameraXCaptureConfig
import dk.kaliv.visionrig.android.CameraXEncodedCapture
import dk.kaliv.visionrig.producer.ControlStepResult
import dk.kaliv.visionrig.producer.EncodedCapture
import dk.kaliv.visionrig.producer.FileProducerStateStore
import dk.kaliv.visionrig.producer.ProducerControlLoop
import dk.kaliv.visionrig.producer.ProducerLoop
import dk.kaliv.visionrig.producer.ProducerRunConfig
import dk.kaliv.visionrig.producer.ProducerRunner
import dk.kaliv.visionrig.producer.ProducerStateIdentity
import dk.kaliv.visionrig.producer.SendStatus
import dk.kaliv.visionrig.producer.VisionRigGatewayClient
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Binds [VisionRigCameraProducer] to VisionRig's vendored producer
 * (android/visionrig-producer, pinned in VENDORED_FROM.json).
 *
 * This builds the same pieces as VisionRig's KalivAndroidProducerSession.create()
 * (state store, gateway client, CameraX capture, control loop), with two
 * differences:
 * - the gateway client is [VisionRigHttp.client]. create() does not pass a
 *   client, so VisionRig would use OkHttpClient(), which follows redirects and
 *   on a 307/308 re-sends a camera frame to another host;
 * - client and camera go through a [VisionRigStopGate], so cancelling the run
 *   (ON_STOP) also stops a control step that is blocked on the gateway.
 *
 * The cadence is VisionRig's own ProducerRunner, unchanged; a thin loop
 * wrapper only reports each control step to the screen.
 */
object VisionRigProducerBinding {
    const val SOURCE_ID = "kaliv-android"
    private const val SOURCE_TYPE = "camera"
    private const val DEVICE = "android-camera"

    val factory = VisionRigCameraProducerFactory { context, lifecycleOwner, connection, http ->
        create(context, lifecycleOwner, connection, http)
    }

    fun create(
        context: Context,
        lifecycleOwner: LifecycleOwner,
        connection: VisionRigConnection,
        http: OkHttpClient,
        runConfig: ProducerRunConfig = ProducerRunConfig(),
        captureFactory: (Context, LifecycleOwner) -> EncodedCapture = { ctx, owner ->
            CameraXEncodedCapture(context = ctx, lifecycleOwner = owner, config = CameraXCaptureConfig())
        },
    ): VisionRigCameraProducer {
        val gate = VisionRigStopGate()
        val stateFile = File(
            context.filesDir,
            "visionrig/" + ProducerStateIdentity(
                gatewayUrl = connection.gatewayUrl,
                sourceId = SOURCE_ID,
                sourceType = SOURCE_TYPE,
            ).defaultStateFileName(),
        )
        val gateway = VisionRigGatewayClient(
            gatewayUrl = connection.gatewayUrl,
            token = connection.token,
            sourceId = SOURCE_ID,
            sourceType = SOURCE_TYPE,
            device = DEVICE,
            stateStore = FileProducerStateStore(stateFile),
            client = gate.client(http),
        )
        val camera = captureFactory(context, lifecycleOwner)
        val loop = ProducerControlLoop(gateway = gateway, capture = gate.capture(camera), capabilities = listOf("rgb", "camerax"))
        return Bound(loop, runConfig, gate) { (camera as? CameraXEncodedCapture)?.shutdown() }
    }

    /** What the screen is told about one control step. Only an ACCEPTED frame counts as sent (review P2). */
    internal fun stepOf(result: ControlStepResult): VisionRigStep {
        val status = result.frameResult?.status
        return VisionRigStep(
            desiredEnabled = result.desiredEnabled,
            captureActive = result.captureActive,
            frameSent = status == SendStatus.ACCEPTED,
            frameDropped = status != null && status != SendStatus.ACCEPTED,
        )
    }

    private class Bound(
        private val loop: ProducerControlLoop,
        private val runConfig: ProducerRunConfig,
        private val gate: VisionRigStopGate,
        private val shutdownCapture: () -> Unit,
    ) : VisionRigCameraProducer {
        private val loopClosed = AtomicBoolean(false)

        /** VisionRig's runner closes the loop in its finally (cancellation closes capture); once is enough. */
        private fun closeLoopOnce() {
            if (loopClosed.compareAndSet(false, true)) loop.close()
        }

        override suspend fun run(onStep: (VisionRigStep) -> Unit) = coroutineScope {
            // Cancellation is only seen between VisionRig's synchronous steps.
            // This watcher sees it at once, on another thread, and stops the
            // gate: the blocked call is cancelled and the step ends without
            // opening the camera or sending a frame.
            val watcher = launch(Dispatchers.IO, start = CoroutineStart.UNDISPATCHED) {
                try {
                    awaitCancellation()
                } finally {
                    gate.stop()
                }
            }
            val observed = object : ProducerLoop {
                override fun step(): ControlStepResult = loop.step().also { result ->
                    if (!gate.isStopped) onStep(stepOf(result))
                }

                override fun close() = closeLoopOnce()
            }
            try {
                ProducerRunner(loop = observed, config = runConfig).run { isActive && !gate.isStopped }
            } catch (e: Exception) {
                // A step that failed because the run was stopped is the stop, not a fault.
                if (!gate.isStopped) throw e
            } finally {
                watcher.cancel()
            }
            Unit
        }

        override fun close() {
            gate.stop()
            try {
                closeLoopOnce()
            } finally {
                shutdownCapture()
            }
        }
    }
}
