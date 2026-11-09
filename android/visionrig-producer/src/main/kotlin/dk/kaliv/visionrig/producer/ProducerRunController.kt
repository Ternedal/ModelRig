package dk.kaliv.visionrig.producer

import java.util.concurrent.atomic.AtomicReference
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

class ProducerRunController(
    private val scope: CoroutineScope,
    private val runnerFactory: () -> ProducerRunner,
) : AutoCloseable {
    private val lifecycleLock = Any()
    private val jobRef = AtomicReference<Job?>(null)

    val isRunning: Boolean
        get() = jobRef.get()?.isActive == true

    fun start(
        shouldContinue: () -> Boolean = { true },
        onCompleted: (Int) -> Unit = {},
        onFailure: (Throwable) -> Unit = {},
    ): Boolean {
        synchronized(lifecycleLock) {
            if (jobRef.get() != null) {
                return false
            }

            lateinit var job: Job
            job = scope.launch(start = CoroutineStart.LAZY) {
                try {
                    val captured = runnerFactory().run(shouldContinue)
                    onCompleted(captured)
                } catch (exc: CancellationException) {
                    throw exc
                } catch (exc: Throwable) {
                    onFailure(exc)
                    throw exc
                } finally {
                    jobRef.compareAndSet(job, null)
                }
            }
            jobRef.set(job)
            job.start()
            return true
        }
    }

    fun stop() {
        synchronized(lifecycleLock) {
            jobRef.get()?.cancel()
        }
    }

    override fun close() {
        stop()
    }
}
