package dk.kaliv.visionrig.android

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Looper
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleOwner
import dk.kaliv.visionrig.producer.EncodedCapture
import dk.kaliv.visionrig.producer.EncodedFrame
import dk.kaliv.visionrig.producer.ProducerProtocolException
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

data class CameraXCaptureConfig(
    val jpegQuality: Int = 85,
    val timeoutSeconds: Long = 10,
    val lensFacing: Int = CameraSelector.LENS_FACING_BACK,
) {
    init {
        require(jpegQuality in 1..100)
        require(timeoutSeconds in 1..60)
        require(
            lensFacing == CameraSelector.LENS_FACING_BACK ||
                lensFacing == CameraSelector.LENS_FACING_FRONT
        )
    }
}

class CameraXEncodedCapture(
    context: Context,
    private val lifecycleOwner: LifecycleOwner,
    private val config: CameraXCaptureConfig = CameraXCaptureConfig(),
) : EncodedCapture {
    private val appContext = context.applicationContext
    private val callbackExecutor = Executors.newSingleThreadExecutor()
    @Volatile private var provider: ProcessCameraProvider? = null
    @Volatile private var imageCapture: ImageCapture? = null

    override val isOpen: Boolean
        get() = provider != null && imageCapture != null

    override fun open() {
        requireWorkerThread()
        if (isOpen) return
        if (
            ContextCompat.checkSelfPermission(appContext, Manifest.permission.CAMERA) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            throw ProducerProtocolException("camera permission is not granted")
        }

        val cameraProvider = try {
            ProcessCameraProvider.getInstance(appContext).get(
                config.timeoutSeconds,
                TimeUnit.SECONDS,
            )
        } catch (exc: Exception) {
            throw ProducerProtocolException("CameraX provider unavailable", exc)
        }

        val capture = ImageCapture.Builder()
            .setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY)
            .setJpegQuality(config.jpegQuality)
            .build()

        val selector = CameraSelector.Builder()
            .requireLensFacing(config.lensFacing)
            .build()

        try {
            runOnMainThread {
                cameraProvider.bindToLifecycle(
                    lifecycleOwner,
                    selector,
                    capture,
                )
            }
        } catch (exc: RuntimeException) {
            scheduleUnbind(cameraProvider, capture)
            throw exc
        }

        provider = cameraProvider
        imageCapture = capture
    }

    override fun capture(): EncodedFrame {
        requireWorkerThread()
        val capture = imageCapture
            ?: throw ProducerProtocolException("CameraX capture is not open")

        val output = File.createTempFile(
            "visionrig-frame-",
            ".jpg",
            appContext.cacheDir,
        )
        val latch = CountDownLatch(1)
        val failure = AtomicReference<Throwable?>()
        val abandoned = AtomicBoolean(false)

        capture.takePicture(
            ImageCapture.OutputFileOptions.Builder(output).build(),
            callbackExecutor,
            object : ImageCapture.OnImageSavedCallback {
                override fun onImageSaved(
                    outputFileResults: ImageCapture.OutputFileResults,
                ) {
                    if (abandoned.get()) {
                        output.delete()
                    }
                    latch.countDown()
                }

                override fun onError(exception: ImageCaptureException) {
                    failure.set(exception)
                    if (abandoned.get()) {
                        output.delete()
                    }
                    latch.countDown()
                }
            },
        )

        val completed = try {
            latch.await(config.timeoutSeconds, TimeUnit.SECONDS)
        } catch (exc: InterruptedException) {
            Thread.currentThread().interrupt()
            abandoned.set(true)
            output.delete()
            throw ProducerProtocolException("CameraX capture interrupted", exc)
        }

        if (!completed) {
            abandoned.set(true)
            output.delete()
            throw ProducerProtocolException("CameraX capture timed out")
        }
        failure.get()?.let { exc ->
            output.delete()
            throw ProducerProtocolException("CameraX capture failed", exc)
        }

        return try {
            val bytes = output.readBytes()
            if (bytes.isEmpty()) {
                throw ProducerProtocolException("CameraX produced an empty JPEG")
            }
            EncodedFrame(bytes = bytes, contentType = "image/jpeg")
        } finally {
            output.delete()
        }
    }

    override fun close() {
        val currentProvider = provider
        val currentCapture = imageCapture
        provider = null
        imageCapture = null

        if (currentProvider != null && currentCapture != null) {
            try {
                runOnMainThread {
                    currentProvider.unbind(currentCapture)
                }
            } catch (_: RuntimeException) {
                // Internal references are already cleared. Cleanup must not mask
                // the original producer/control failure that triggered close().
            }
        }
    }

    fun shutdown() {
        try {
            close()
        } finally {
            callbackExecutor.shutdownNow()
        }
    }


    private fun scheduleUnbind(
        cameraProvider: ProcessCameraProvider,
        capture: ImageCapture,
    ) {
        ContextCompat.getMainExecutor(appContext).execute {
            try {
                cameraProvider.unbind(capture)
            } catch (_: RuntimeException) {
            }
        }
    }

    private fun requireWorkerThread() {
        if (Looper.myLooper() == Looper.getMainLooper()) {
            throw ProducerProtocolException(
                "CameraX producer operations must run off the Android main thread"
            )
        }
    }

    private fun runOnMainThread(block: () -> Unit) {
        if (Looper.myLooper() == Looper.getMainLooper()) {
            block()
            return
        }

        val latch = CountDownLatch(1)
        val failure = AtomicReference<Throwable?>()
        ContextCompat.getMainExecutor(appContext).execute {
            try {
                block()
            } catch (exc: Throwable) {
                failure.set(exc)
            } finally {
                latch.countDown()
            }
        }

        val completed = try {
            latch.await(config.timeoutSeconds, TimeUnit.SECONDS)
        } catch (exc: InterruptedException) {
            Thread.currentThread().interrupt()
            throw ProducerProtocolException("CameraX main-thread operation interrupted", exc)
        }

        if (!completed) {
            throw ProducerProtocolException("CameraX main-thread operation timed out")
        }
        failure.get()?.let { exc ->
            throw ProducerProtocolException("CameraX lifecycle binding failed", exc)
        }
    }
}
