package dk.ternedal.modelrig.net

import android.content.Context
import androidx.lifecycle.LifecycleOwner
import dk.kaliv.visionrig.android.CameraXCaptureConfig
import dk.kaliv.visionrig.android.CameraXEncodedCapture
import dk.kaliv.visionrig.producer.ControlStepResult
import dk.kaliv.visionrig.producer.FileProducerStateStore
import dk.kaliv.visionrig.producer.ProducerControlLoop
import dk.kaliv.visionrig.producer.ProducerLoop
import dk.kaliv.visionrig.producer.ProducerRunConfig
import dk.kaliv.visionrig.producer.ProducerRunner
import dk.kaliv.visionrig.producer.ProducerStateIdentity
import dk.kaliv.visionrig.producer.VisionRigGatewayClient
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.isActive
import okhttp3.OkHttpClient
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Binds [VisionRigCameraProducer] to VisionRig's vendored producer
 * (src/visionrigVendored, pinned in VENDORED_FROM.json).
 *
 * This builds the same pieces as VisionRig's KalivAndroidProducerSession.create()
 * (state store, gateway client, CameraX capture, control loop), with one
 * difference: the gateway client gets [VisionRigHttp.client]. create() does not
 * pass a client, so VisionRig would use OkHttpClient(), which follows redirects
 * and on a 307/308 re-sends a camera frame to another host.
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
        captureFactory: (Context, LifecycleOwner) -> CameraXEncodedCapture = { ctx, owner ->
            CameraXEncodedCapture(context = ctx, lifecycleOwner = owner, config = CameraXCaptureConfig())
        },
    ): VisionRigCameraProducer {
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
            client = http,
        )
        val capture = captureFactory(context, lifecycleOwner)
        val loop = ProducerControlLoop(gateway = gateway, capture = capture, capabilities = listOf("rgb", "camerax"))
        return Bound(loop, runConfig) { capture.shutdown() }
    }

    private class Bound(
        private val loop: ProducerControlLoop,
        private val runConfig: ProducerRunConfig,
        private val shutdownCapture: () -> Unit,
    ) : VisionRigCameraProducer {
        private val loopClosed = AtomicBoolean(false)

        /** VisionRig's runner closes the loop in its finally (cancellation closes capture); once is enough. */
        private fun closeLoopOnce() {
            if (loopClosed.compareAndSet(false, true)) loop.close()
        }

        override suspend fun run(onStep: (VisionRigStep) -> Unit) {
            val observed = object : ProducerLoop {
                override fun step(): ControlStepResult = loop.step().also { result ->
                    onStep(
                        VisionRigStep(
                            desiredEnabled = result.desiredEnabled,
                            captureActive = result.captureActive,
                            frameSent = result.frameResult != null,
                        ),
                    )
                }

                override fun close() = closeLoopOnce()
            }
            val context = currentCoroutineContext()
            ProducerRunner(loop = observed, config = runConfig).run { context.isActive }
        }

        override fun close() {
            try {
                closeLoopOnce()
            } finally {
                shutdownCapture()
            }
        }
    }
}
