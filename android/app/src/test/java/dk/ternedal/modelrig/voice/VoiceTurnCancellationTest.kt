package dk.ternedal.modelrig.voice

import okhttp3.OkHttpClient
import okhttp3.Request
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class VoiceTurnCancellationTest {
    private fun newCall() = OkHttpClient().newCall(
        Request.Builder().url("http://127.0.0.1:8102/voice/converse/stream").build()
    )

    @Test fun stopClosesTheRegisteredVoiceNetworkStream() {
        val controller = VoiceTurnCancellation()
        val call = newCall()
        controller.register(call)

        assertFalse(call.isCanceled())
        assertFalse(controller.stopFlag.get())

        controller.stop()
        assertTrue(call.isCanceled())
        assertTrue(controller.stopFlag.get())
    }

    @Test fun stopBeforeCallRegistrationStillCancelsIt() {
        val controller = VoiceTurnCancellation()
        controller.stop()

        val call = newCall()
        controller.register(call)

        assertTrue(call.isCanceled())
        assertTrue(controller.stopFlag.get())
    }

    @Test fun oldTurnStopDoesNotCancelAnUnrelatedNewTurn() {
        val first = VoiceTurnCancellation()
        val second = VoiceTurnCancellation()
        val oldCall = newCall()
        val newCall = newCall()

        first.register(oldCall)
        second.register(newCall)
        first.stop()

        assertTrue(oldCall.isCanceled())
        assertFalse(newCall.isCanceled())
        assertFalse(second.stopFlag.get())
    }

    @Test fun clearDoesNotCancelAlreadyCompletedCall() {
        val controller = VoiceTurnCancellation()
        val call = newCall()
        controller.register(call)
        controller.clear()
        controller.stop()

        assertFalse(call.isCanceled())
        assertTrue(controller.stopFlag.get())
    }

    @Test fun repeatedStopIsIdempotent() {
        val controller = VoiceTurnCancellation()
        val call = newCall()
        controller.register(call)

        controller.stop()
        controller.stop()

        assertTrue(call.isCanceled())
    }
}
