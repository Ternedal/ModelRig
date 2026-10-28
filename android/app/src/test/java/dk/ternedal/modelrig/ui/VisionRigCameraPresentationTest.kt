package dk.ternedal.modelrig.ui

import dk.ternedal.modelrig.net.VisionRigOriginRefusedIOException
import dk.ternedal.modelrig.net.VisionRigStep
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException

class VisionRigCameraPresentationTest {
    private fun step(enabled: Boolean, sent: Boolean) = VisionRigStep(desiredEnabled = enabled, captureActive = enabled, frameSent = sent)

    @Test
    fun `frames are counted only while VisionRig enables the source`() {
        var s: VisionRigCameraStatus = VisionRigCameraStatus.Starting
        s = VisionRigCameraPresentation.afterStep(s, step(enabled = false, sent = false))
        assertEquals(VisionRigCameraStatus.WaitingForRig, s)
        s = VisionRigCameraPresentation.afterStep(s, step(enabled = true, sent = true))
        s = VisionRigCameraPresentation.afterStep(s, step(enabled = true, sent = false))
        s = VisionRigCameraPresentation.afterStep(s, step(enabled = true, sent = true))
        assertEquals(VisionRigCameraStatus.Capturing(2), s)
        assertEquals(VisionRigCameraStatus.WaitingForRig, VisionRigCameraPresentation.afterStep(s, step(enabled = false, sent = false)))
    }

    @Test
    fun `banner state follows a running producer only`() {
        assertTrue(VisionRigCameraStatus.Starting.producerRunning)
        assertTrue(VisionRigCameraStatus.WaitingForRig.producerRunning)
        assertTrue(VisionRigCameraStatus.Capturing(0).producerRunning)
        assertFalse(VisionRigCameraStatus.Stopped.producerRunning)
        assertFalse(VisionRigCameraStatus.Failed("x").producerRunning)
    }

    @Test
    fun `failures get danish text without detail`() {
        val texts = listOf(
            VisionRigCameraPresentation.failure(VisionRigOriginRefusedIOException("secret-ish detail")),
            VisionRigCameraPresentation.failure(IOException("http://192.168.1.10:8111 token=abc")),
            VisionRigCameraPresentation.failure(SecurityException("camera")),
            VisionRigCameraPresentation.failure(IllegalStateException("boom")),
        ).map { it.message }
        assertEquals(4, texts.toSet().size)
        assertTrue(texts.none { it.contains("token") || it.contains("detail") || it.contains("192.168") })
    }
}
