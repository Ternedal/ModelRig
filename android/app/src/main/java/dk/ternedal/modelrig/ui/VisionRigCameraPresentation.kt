package dk.ternedal.modelrig.ui

import dk.ternedal.modelrig.net.VisionRigOriginRefusedIOException
import dk.ternedal.modelrig.net.VisionRigStep
import java.io.IOException

/** What the camera screen shows about the producer. Pure data. */
sealed class VisionRigCameraStatus {
    /** Not running: opt-in off, permission missing, or the screen is not in the foreground. */
    data object Stopped : VisionRigCameraStatus()
    data object Starting : VisionRigCameraStatus()
    /** Connected; VisionRig's desired-state keeps the camera closed. Nothing is sent. */
    data object WaitingForRig : VisionRigCameraStatus()
    /** [framesSent] counts frames VisionRig accepted; [framesDropped] those it did not get. */
    data class Capturing(val framesSent: Int, val framesDropped: Int = 0) : VisionRigCameraStatus()
    data class Failed(val message: String) : VisionRigCameraStatus()

    /** The banner "Kamera sendes til riggen" is shown whenever the producer is running. */
    val producerRunning: Boolean get() = this is Starting || this is WaitingForRig || this is Capturing
}

object VisionRigCameraPresentation {
    fun afterStep(current: VisionRigCameraStatus, step: VisionRigStep): VisionRigCameraStatus {
        if (!step.desiredEnabled) return VisionRigCameraStatus.WaitingForRig
        val before = current as? VisionRigCameraStatus.Capturing
        return VisionRigCameraStatus.Capturing(
            framesSent = (before?.framesSent ?: 0) + if (step.frameSent) 1 else 0,
            framesDropped = (before?.framesDropped ?: 0) + if (step.frameDropped) 1 else 0,
        )
    }

    /** Danish text for a producer failure; never the token, never server detail. */
    fun failure(error: Throwable): VisionRigCameraStatus.Failed = VisionRigCameraStatus.Failed(
        when (error) {
            is VisionRigOriginRefusedIOException -> "En forespørgsel uden for den parrede VisionRig blev afvist."
            is IOException -> "VisionRig kan ikke nås. Tjek at gatewayen kører, og at telefonen er på samme netværk."
            is SecurityException -> "Kameraet er ikke tilgængeligt. Tjek kamera-tilladelsen."
            else -> "VisionRig-producenten stoppede (${error::class.simpleName ?: "fejl"})."
        },
    )

    fun statusText(status: VisionRigCameraStatus): String = when (status) {
        VisionRigCameraStatus.Stopped -> "Kameraet sendes ikke."
        VisionRigCameraStatus.Starting -> "Forbinder til VisionRig…"
        VisionRigCameraStatus.WaitingForRig -> "VisionRig har ikke slået kameraet til. Intet sendes."
        is VisionRigCameraStatus.Capturing ->
            "Sender billeder til VisionRig: ${status.framesSent} modtaget" +
                if (status.framesDropped > 0) ", ${status.framesDropped} tabt (VisionRig optaget eller utilgængelig)" else ""
        is VisionRigCameraStatus.Failed -> status.message
    }
}
