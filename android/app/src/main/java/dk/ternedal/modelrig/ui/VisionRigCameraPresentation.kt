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
    data class Capturing(val framesSent: Int) : VisionRigCameraStatus()
    data class Failed(val message: String) : VisionRigCameraStatus()

    /** The banner "Kamera sendes til riggen" is shown whenever the producer is running. */
    val producerRunning: Boolean get() = this is Starting || this is WaitingForRig || this is Capturing
}

object VisionRigCameraPresentation {
    fun afterStep(current: VisionRigCameraStatus, step: VisionRigStep): VisionRigCameraStatus {
        if (!step.desiredEnabled) return VisionRigCameraStatus.WaitingForRig
        val sent = (current as? VisionRigCameraStatus.Capturing)?.framesSent ?: 0
        return VisionRigCameraStatus.Capturing(sent + if (step.frameSent) 1 else 0)
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
        is VisionRigCameraStatus.Capturing -> "Sender billeder til VisionRig: ${status.framesSent}"
        is VisionRigCameraStatus.Failed -> status.message
    }
}
