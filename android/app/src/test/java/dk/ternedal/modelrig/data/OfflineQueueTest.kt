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

    @Test
    fun `loftet er et rigtigt tal`() {
        assertTrue(OfflineQueue.MAX in 5..100)
    }
}
