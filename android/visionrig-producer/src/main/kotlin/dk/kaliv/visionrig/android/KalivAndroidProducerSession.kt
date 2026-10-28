package dk.kaliv.visionrig.android

import android.content.Context
import androidx.lifecycle.LifecycleOwner
import dk.kaliv.visionrig.producer.ControlStepResult
import dk.kaliv.visionrig.producer.FileProducerStateStore
import dk.kaliv.visionrig.producer.ProducerControlLoop
import dk.kaliv.visionrig.producer.ProducerRunConfig
import dk.kaliv.visionrig.producer.ProducerRunner
import dk.kaliv.visionrig.producer.ProducerStateIdentity
import dk.kaliv.visionrig.producer.VisionRigGatewayClient
import java.io.File

class KalivAndroidProducerSession private constructor(
    private val controlLoop: ProducerControlLoop,
    private val capture: CameraXEncodedCapture,
) : AutoCloseable {
    fun step(): ControlStepResult = controlLoop.step()

    suspend fun run(
        config: ProducerRunConfig = ProducerRunConfig(),
        shouldContinue: () -> Boolean = { true },
    ): Int = ProducerRunner(
        loop = controlLoop,
        config = config,
    ).run(shouldContinue)

    override fun close() {
        try {
            controlLoop.close()
        } finally {
            capture.shutdown()
        }
    }

    companion object {
        fun create(
            context: Context,
            lifecycleOwner: LifecycleOwner,
            gatewayUrl: String,
            token: String,
            sourceId: String = "kaliv-android",
            device: String = "android-camera",
            stateFile: File = File(
                context.filesDir,
                "visionrig/" + ProducerStateIdentity(
                    gatewayUrl = gatewayUrl,
                    sourceId = sourceId,
                    sourceType = "camera",
                ).defaultStateFileName(),
            ),
            captureConfig: CameraXCaptureConfig = CameraXCaptureConfig(),
        ): KalivAndroidProducerSession {
            val store = FileProducerStateStore(stateFile)
            val gateway = VisionRigGatewayClient(
                gatewayUrl = gatewayUrl,
                token = token,
                sourceId = sourceId,
                sourceType = "camera",
                device = device,
                stateStore = store,
            )
            val capture = CameraXEncodedCapture(
                context = context,
                lifecycleOwner = lifecycleOwner,
                config = captureConfig,
            )
            val loop = ProducerControlLoop(
                gateway = gateway,
                capture = capture,
                capabilities = listOf("rgb", "camerax"),
            )
            return KalivAndroidProducerSession(loop, capture)
        }
    }
}
