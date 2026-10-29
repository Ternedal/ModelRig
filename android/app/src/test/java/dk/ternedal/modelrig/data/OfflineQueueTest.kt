package dk.ternedal.modelrig.data

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class OfflineQueueTest {

    private fun json(vararg items: Pair<String, Long>): String {
        val arr = JSONArray()
        items.forEach { arr.put(JSONObject().put("text", it.first).put("at", it.second)) }
        return arr.toString()
    }

    @Test
    fun `koeen laeses tilbage i samme raekkefoelge`() {
        val items = OfflineQueue.parse(json("en" to 1L, "to" to 2L))
        assertEquals(listOf("en", "to"), items.map { it.text })
        assertEquals(listOf(1L, 2L), items.map { it.atMillis })
    }

    @Test
    fun `ulaeselig koe giver en TOM koe, ikke et crash`() {
        assertEquals(emptyList<OfflineQueue.Item>(), OfflineQueue.parse("{ ikke json"))
        assertEquals(emptyList<OfflineQueue.Item>(), OfflineQueue.parse(""))
        assertEquals(emptyList<OfflineQueue.Item>(), OfflineQueue.parse(null))
    }

    @Test
    fun `tomme beskeder er ikke i koeen`() {
        assertEquals(1, OfflineQueue.parse(json("   " to 1L, "rigtig" to 2L)).size)
    }

    @Test
    fun `tidsstempel skrives ud saa man kan bedoemme om beskeden stadig gaelder`() {
        val now = 1_700_000_000_000L
        assertTrue(OfflineQueue.writtenLabel(now, now).startsWith("skrevet "))
        assertTrue(OfflineQueue.writtenLabel(now - 24 * 3600 * 1000L, now).contains("i går"))
        assertEquals("skrevet tidligere", OfflineQueue.writtenLabel(0L, now))
    }

    private fun utc(text: String) = java.time.Instant.parse(text).toEpochMilli()

    @Test
    fun `etiketten foelger den givne tidszone, ikke maskinens`() {
        val at = utc("2023-11-14T23:30:00Z")
        val now = utc("2023-11-15T00:30:00Z")
        assertEquals("skrevet i går 23:30", OfflineQueue.writtenLabel(at, now, java.time.ZoneOffset.UTC))
        // Same instants in Copenhagen (UTC+1): both on 15/11.
        assertEquals("skrevet 00:30", OfflineQueue.writtenLabel(at, now, java.time.ZoneId.of("Europe/Copenhagen")))
    }

    @Test
    fun `nytaarsaften er i gaar den 1 januar`() {
        val at = utc("2023-12-31T20:00:00Z")
        val now = utc("2024-01-01T09:00:00Z")
        assertEquals("skrevet i går 20:00", OfflineQueue.writtenLabel(at, now, java.time.ZoneOffset.UTC))
    }

    @Test
    fun `aeldre end i gaar viser dato`() {
        val at = utc("2023-11-12T08:05:00Z")
        val now = utc("2023-11-14T12:00:00Z")
        assertEquals("skrevet 12/11 08:05", OfflineQueue.writtenLabel(at, now, java.time.ZoneOffset.UTC))
    }

    @Test
    fun `loftet er et rigtigt tal`() {
        assertTrue(OfflineQueue.MAX in 5..100)
    }
}
