package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Bekraeftelsen binder HVAD MENNESKET SAA til HVAD DER UDFOERES.
 *
 * Serveren udleverer en digest sammen med det trin der venter paa godkendelse.
 * Klienten skal sende praecis den tilbage -- ikke en genberegnet, ikke et andet
 * trins, ikke en tom streng. Goer den noget andet, er godkendelsen afkoblet fra
 * handlingen, og et menneske har sagt ja til noget det ikke saa.
 *
 * Worker-siden af Agent 3 har 61 python-testfiler. Klientsiden -- 26 filer og
 * ~6400 linjer, inklusive den her sti -- havde nul, indtil 27/07-2026. Det er
 * den forkerte vej rundt: klienten er dér godkendelsen opsamles.
 *
 * Implementeringen er korrekt i dag. Testen findes for at holde den der.
 */
class Agent3ConfirmationContractTest {

    private fun jsonResponse(body: String) =
        MockResponse().setHeader("Content-Type", "application/json").setBody(body)

    private fun runEnvelope(state: String) = """
        {"run":{"id":"run-1","plan_id":"plan-1","state":"$state","steps":[]}}
    """.trimIndent()

    @Test
    fun confirmSendsBackExactlyTheDigestItWasGiven() {
        val digest = "9f2c4a10bb7e4d6f8a1c3e5079b2d4f68a0c1e3579bd2f4608ace1357bd9f024"
        val server = MockWebServer()
        server.enqueue(jsonResponse(runEnvelope("running")))
        server.start()
        try {
            val client = Agent3Client(server.url("/").toString(), "device-token")
            client.confirm(runId = "run-1", stepId = "step-2", digest = digest, approve = true)

            val recorded = server.takeRequest()
            val body = JSONObject(recorded.body.readUtf8())

            // Byte for byte. En transformation her ville vaere usynlig i UI'et
            // og fatal i betydning.
            assertEquals(digest, body.getString("digest"))
            assertEquals("step-2", body.getString("step_id"))
            assertEquals("approve", body.getString("decision"))
            assertTrue(
                "ruten skal ligge under /experimental/, saa en klient ikke rammer " +
                    "den ved et uheld",
                recorded.path!!.contains("/experimental/agent3/runs/run-1/confirm"),
            )
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun denyIsSentAsDenyAndNotAsAnAbsentApproval() {
        // En afvisning skal vaere et eksplicit "deny". Sendes feltet slet ikke,
        // eller sendes "approve": false, kan en server som laeser feltet
        // permissivt komme til at behandle det som en godkendelse.
        val server = MockWebServer()
        server.enqueue(jsonResponse(runEnvelope("denied")))
        server.start()
        try {
            val client = Agent3Client(server.url("/").toString(), "device-token")
            client.confirm(runId = "run-1", stepId = "step-2", digest = "abc", approve = false)

            val body = JSONObject(server.takeRequest().body.readUtf8())
            assertEquals("deny", body.getString("decision"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun twoStepsWithDifferentDigestsDoNotShareOne() {
        // Kontrolpunkt. Uden det kunne foerste test bestaa selv hvis klienten
        // sendte en konstant.
        val first = "1111111111111111111111111111111111111111111111111111111111111111"
        val second = "2222222222222222222222222222222222222222222222222222222222222222"
        val server = MockWebServer()
        server.enqueue(jsonResponse(runEnvelope("running")))
        server.enqueue(jsonResponse(runEnvelope("running")))
        server.start()
        try {
            val client = Agent3Client(server.url("/").toString(), "device-token")
            client.confirm("run-1", "step-1", first, approve = true)
            client.confirm("run-1", "step-2", second, approve = true)

            val a = JSONObject(server.takeRequest().body.readUtf8())
            val b = JSONObject(server.takeRequest().body.readUtf8())
            assertEquals(first, a.getString("digest"))
            assertEquals(second, b.getString("digest"))
        } finally {
            server.shutdown()
        }
    }
}
