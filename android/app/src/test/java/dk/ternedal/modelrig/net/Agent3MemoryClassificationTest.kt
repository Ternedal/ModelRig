package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * En hukommelses klassifikation maa ikke kunne forsvinde undervejs.
 *
 * Maalt 27/07-2026: udelader serveren feltet, parser klienten det som "" --
 * optString giver tom streng, ikke null. Agent3MemoryScreen forudfylder
 * redigeringsfeltet med den vaerdi, saa en rettelse ville sende
 * `sensitivity: ""` tilbage. En hukommelse der var `secret` ville blive gemt
 * uden at vaere det, og intet i UI'et ville vise forskellen.
 *
 * Laesestien er bevidst uroert -- at lade den kaste kunne braekke klienten mod
 * en serverversion der legitimt udelader feltet. Vagten sidder paa SKRIVESTIEN,
 * hvor konsekvensen er.
 */
class Agent3MemoryClassificationTest {

    private fun memoryResponse(sensitivity: String?) = MockResponse()
        .setHeader("Content-Type", "application/json")
        .setBody(
            buildString {
                append("""{"memory":{"id":"m1","subject":"s","predicate":"p","value":"v","kind":"fact"""")
                if (sensitivity != null) append(""","sensitivity":"$sensitivity"""")
                append("}}")
            },
        )

    @Test
    fun createSendsTheClassificationItWasGiven() {
        val s = MockWebServer()
        s.enqueue(memoryResponse("secret"))
        s.start()
        try {
            Agent3MemoryClient(s.url("/").toString(), "t")
                .create("subj", "pred", "value", "fact", "secret")
            val body = JSONObject(s.takeRequest().body.readUtf8())
            assertEquals("secret", body.getString("sensitivity"))
        } finally {
            s.shutdown()
        }
    }

    @Test
    fun correctRestatesTheClassification() {
        // En rettelse skal baere klassifikationen med. Gjorde den ikke det,
        // ville en serverside der laeser permissivt kunne nulstille den.
        val s = MockWebServer()
        s.enqueue(memoryResponse("private"))
        s.start()
        try {
            Agent3MemoryClient(s.url("/").toString(), "t")
                .correct("m1", "ny vaerdi", "private")
            val body = JSONObject(s.takeRequest().body.readUtf8())
            assertEquals("private", body.getString("sensitivity"))
            assertEquals("ny vaerdi", body.getString("value"))
        } finally {
            s.shutdown()
        }
    }

    @Test
    fun aBlankClassificationIsRefusedOnWrite() {
        val s = MockWebServer()
        s.start()
        try {
            val c = Agent3MemoryClient(s.url("/").toString(), "t")
            for (blank in listOf("", "   ")) {
                var refused = false
                try {
                    c.correct("m1", "v", blank)
                } catch (e: ModelRigException) {
                    refused = true
                }
                assertTrue("correct skal afvise sensitivity=${blank.length} blanke tegn", refused)

                refused = false
                try {
                    c.create("s", "p", "v", "fact", blank)
                } catch (e: ModelRigException) {
                    refused = true
                }
                assertTrue("create skal afvise en blank klassifikation", refused)
            }
            assertEquals("intet maa vaere sendt", 0, s.requestCount)
        } finally {
            s.shutdown()
        }
    }

    @Test
    fun aMissingFieldStillParsesSoReadsDoNotBreak() {
        // Kontrolpunkt for den bevidste asymmetri: laesning er tolerant,
        // skrivning er streng. Uden denne test ville nogen "rette" laesningen
        // til ogsaa at kaste og braekke klienten mod en aeldre server.
        val s = MockWebServer()
        s.enqueue(memoryResponse(null))
        s.start()
        try {
            val m = Agent3MemoryClient(s.url("/").toString(), "t")
                .create("s", "p", "v", "fact", "public")
            assertEquals("", m.sensitivity)
        } finally {
            s.shutdown()
        }
    }
}
