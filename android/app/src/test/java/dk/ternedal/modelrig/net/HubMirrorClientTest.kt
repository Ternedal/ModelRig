package dk.ternedal.modelrig.net

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Entirely offline tests; no Android device, secrets, or network services. */
class HubMirrorClientTest {
    @Test fun acceptsOnlyExplicitPrivateIpEndpoints() {
        assertEquals(
            "http://192.168.1.100:8765/v1/events",
            HubMirrorClient.endpoint("http://192.168.1.100:8765"),
        )
        assertEquals(
            "http://10.1.2.3:8765/v1/events",
            HubMirrorClient.endpoint("http://10.1.2.3:8765/v1/events"),
        )
        assertEquals(
            "http://100.100.3.4:8765/v1/events",
            HubMirrorClient.endpoint("http://100.100.3.4:8765/"),
        )
        assertTrue(HubMirrorClient.privateIpv4("172.16.0.10"))
        assertTrue(HubMirrorClient.privateIpv4("172.31.255.254"))
        assertFalse(HubMirrorClient.privateIpv4("172.32.0.2"))
    }

    @Test fun rejectsRemoteOrTrickyEndpoints() {
        listOf(
            "https://192.168.1.100:8765",
            "http://192.168.1.100", // explicit port required
            "http://example.com:8765",
            "http://8.8.8.8:8765",
            "http://127.0.0.1:8765",
            "http://169.254.3.4:8765",
            "http://192.168.1.100:8765/admin",
            "http://192.168.1.100:8765/?next=cloud",
            "http://user:pass@192.168.1.100:8765",
            "http://192.168.1.100:8765#secret",
            "http://192.168.1.010:8765",
            "http://0.0.0.0:8765",
        ).forEach { bad ->
            assertNull("Unexpectedly accepted $bad", HubMirrorClient.endpoint(bad))
        }
    }

    @Test fun clipsUtf16TextWithoutBreakingSurrogatePairs() {
        assertEquals(2000, HubMirrorClient.limitVisibleText("x".repeat(5000)).length)
        assertEquals(2000, HubMirrorClient.limitVisibleText("😀".repeat(2000)).length)
        assertEquals(
            1999,
            HubMirrorClient.limitVisibleText("x".repeat(1999) + "😀").length,
        )
        assertEquals("Hej", HubMirrorClient.limitVisibleText(" \n Hej \n "))
        assertEquals("", HubMirrorClient.limitVisibleText("  "))
    }

    @Test fun queuedRepliesAreRevokedOnDisableOrKeyRotation() {
        val originalGeneration = 41L
        assertTrue(HubMirrorClient.mayDeliver(true, originalGeneration, originalGeneration))
        assertFalse(HubMirrorClient.mayDeliver(false, originalGeneration + 1, originalGeneration))
        assertFalse(HubMirrorClient.mayDeliver(true, originalGeneration + 2, originalGeneration))
        assertFalse(HubMirrorClient.mayDeliver(true, originalGeneration + 1, originalGeneration))
        assertTrue(HubMirrorClient.mayDeliver(true, originalGeneration + 2, originalGeneration + 2))
    }

    @Test fun deterministicSignatureMatchesPythonHmacSha256() {
        val body = "{\"version\":1,\"type\":\"assistant_complete\"," +
            "\"event_id\":\"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa\",\"text\":\"Hej\"}"
        assertEquals(
            "v1=2bbcd5f9211630bd07c02821477a3f78739305216d244c0d9d18b4ad06a6866e",
            HubMirrorClient.signature("s".repeat(40), "1700000000", body),
        )
    }
}
