package dk.kaliv.visionrig.producer

import kotlin.math.max
import kotlin.math.roundToLong
import kotlinx.coroutines.delay

data class ProducerRunConfig(
    val fps: Double = 5.0,
    val disabledPollMillis: Long = 2_000,
    val maxFrames: Int = 0,
) {
    init {
        require(fps > 0.0 && fps <= 60.0)
        require(disabledPollMillis in 250..60_000)
        require(maxFrames >= 0)
    }

    val enabledFrameDelayMillis: Long
        get() = max(1L, (1_000.0 / fps).roundToLong())
}

class ProducerRunner(
    private val loop: ProducerLoop,
    private val config: ProducerRunConfig = ProducerRunConfig(),
    private val delayMillis: suspend (Long) -> Unit = { delay(it) },
) {
    suspend fun run(
        shouldContinue: () -> Boolean = { true },
    ): Int {
        var capturedFrames = 0
        var primaryFailure: Throwable? = null
        try {
            while (
                shouldContinue() &&
                (config.maxFrames == 0 || capturedFrames < config.maxFrames)
            ) {
                val step = loop.step()
                if (step.frameResult != null) {
                    capturedFrames += 1
                }

                if (
                    config.maxFrames > 0 &&
                    capturedFrames >= config.maxFrames
                ) {
                    break
                }

                val reachedFrameLimit =
                    config.maxFrames > 0 && capturedFrames >= config.maxFrames
                if (!reachedFrameLimit) {
                    val sleepMillis = if (step.desiredEnabled) {
                        config.enabledFrameDelayMillis
                    } else {
                        config.disabledPollMillis
                    }
                    delayMillis(sleepMillis)
                }
            }
            return capturedFrames
        } catch (exc: Throwable) {
            primaryFailure = exc
            throw exc
        } finally {
            try {
                loop.close()
            } catch (closeFailure: Throwable) {
                if (primaryFailure != null) {
                    primaryFailure.addSuppressed(closeFailure)
                } else {
                    throw closeFailure
                }
            }
        }
    }
}
