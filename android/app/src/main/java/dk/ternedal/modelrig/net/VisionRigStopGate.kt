package dk.ternedal.modelrig.net

import dk.kaliv.visionrig.producer.EncodedCapture
import dk.kaliv.visionrig.producer.EncodedFrame
import okhttp3.Dispatcher
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import java.io.IOException
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Stops one producer run at once, including inside a blocking control step
 * (#2303 review 5688431923, P1).
 *
 * VisionRig's ProducerControlLoop.step() is synchronous: desired-state, camera
 * open, heartbeat, capture, frame POST. Coroutine cancellation (ON_STOP) is
 * only seen between steps, so without this a slow desired-state answer could
 * still open the camera and send a frame after the screen stopped. After [stop]:
 * - every call on [client] that is in flight is cancelled, and no new request
 *   leaves the phone;
 * - a response that arrives after stop is closed unread, so a late "enabled"
 *   is never acted on;
 * - the camera refuses to open, and a frame captured across the stop is
 *   discarded.
 *
 * One gate per producer, one producer per run.
 */
internal class VisionRigStopGate {
    private val stopped = AtomicBoolean(false)

    /** Its own dispatcher, so [stop] cancels this producer's calls and nothing else. */
    private val dispatcher = Dispatcher()

    val isStopped: Boolean get() = stopped.get()

    fun stop() {
        if (stopped.compareAndSet(false, true)) dispatcher.cancelAll()
    }

    private fun refuseIfStopped() {
        if (stopped.get()) throw VisionRigStoppedIOException()
    }

    /**
     * [guarded] is [VisionRigHttp.client]. newBuilder() keeps its interceptors
     * and its redirect settings; this only adds the stop check in front of the
     * network and after it.
     */
    fun client(guarded: OkHttpClient): OkHttpClient = guarded.newBuilder()
        .dispatcher(dispatcher)
        .addInterceptor(Interceptor { chain ->
            refuseIfStopped()
            val response = chain.proceed(chain.request())
            if (stopped.get()) {
                response.close()
                throw VisionRigStoppedIOException()
            }
            response
        })
        .build()

    fun capture(camera: EncodedCapture): EncodedCapture = object : EncodedCapture {
        override val isOpen: Boolean get() = camera.isOpen

        override fun open() {
            refuseIfStopped()
            camera.open()
            if (stopped.get()) {
                camera.close()
                throw VisionRigStoppedIOException()
            }
        }

        override fun close() = camera.close()

        override fun capture(): EncodedFrame {
            refuseIfStopped()
            val frame = camera.capture()
            refuseIfStopped()
            return frame
        }
    }
}

/** The producer was stopped (ON_STOP or close); nothing more is sent. */
class VisionRigStoppedIOException : IOException("VisionRig producer stopped")
