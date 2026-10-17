package dk.ternedal.modelrig.logic

import org.junit.Assert.assertEquals
import org.junit.Test

class CloudFallbackPolicyTest {
    @Test fun privacyAndCancellationMatrix() {
        for (emitted in listOf(0, 1, 20)) {
            for (cancelled in listOf(false, true)) {
                for (key in listOf(false, true)) {
                    for (consent in listOf(false, true)) {
                        val expected = emitted == 0 && !cancelled && key && consent
                        assertEquals(
                            "emitted=$emitted cancelled=$cancelled key=$key consent=$consent",
                            expected,
                            CloudFallbackPolicy.shouldFallback(emitted, cancelled, key, consent),
                        )
                    }
                }
            }
        }
    }

    @Test fun cancelledBeforeFirstTokenNeverEscapesToCloud() {
        assertEquals(false, CloudFallbackPolicy.shouldFallback(0, true, true, true))
    }

    @Test fun partialLocalAnswerIsNeverReplayedToCloud() {
        assertEquals(false, CloudFallbackPolicy.shouldFallback(1, false, true, true))
    }

    @Test fun explicitConsentAllowsPreTokenRecovery() {
        assertEquals(true, CloudFallbackPolicy.shouldFallback(0, false, true, true))
    }
}
