package dk.ternedal.modelrig.data

import org.json.JSONArray
import org.json.JSONObject

/**
 * Beskeder skrevet mens riggen var væk.
 *
 * DEN BÆRENDE REGEL: en besked i kø sendes ALDRIG af sig selv. Når riggen
 * kommer tilbage, viser appen køen og venter på et tryk. Automatisk afsendelse
 * ville besvare noget du skrev i en anden situation — måske timer før, måske
 * om noget du siden har løst selv.
 *
 * Køen er telefonens eget regnskab: riggen ved intet om den, og forsvinder
 * den, forsvinder kun en påmindelse — aldrig et svar.
 */
class OfflineQueue(private val prefs: android.content.SharedPreferences) {

    data class Item(val text: String, val atMillis: Long)

    fun all(): List<Item> = parse(prefs.getString(KEY, null))

    /** Lægger en besked bagerst. Tom tekst afvises; køen er ikke en papirkurv. */
    fun add(text: String, atMillis: Long): List<Item> {
        val t = text.trim()
        if (t.isEmpty()) return all()
        val next = (all() + Item(t, atMillis)).takeLast(MAX)
        save(next)
        return next
    }

    fun remove(item: Item): List<Item> {
        val next = all().filterNot { it.text == item.text && it.atMillis == item.atMillis }
        save(next)
        return next
    }

    fun clear() = save(emptyList())

    private fun save(items: List<Item>) {
        val arr = JSONArray()
        items.forEach { arr.put(JSONObject().put("text", it.text).put("at", it.atMillis)) }
        prefs.edit().putString(KEY, arr.toString()).apply()
    }

    companion object {
        private const val KEY = "offline_queue"

        /** Loft. En kø der vokser i det uendelige er en seddelbunke, ikke en hjælp. */
        const val MAX = 20

        /** Læser køen fail-soft: ulæselig JSON giver en tom kø, ikke et crash. */
        fun parse(raw: String?): List<Item> {
            if (raw.isNullOrBlank()) return emptyList()
            return runCatching {
                val arr = JSONArray(raw)
                (0 until arr.length()).mapNotNull { i ->
                    val o = arr.optJSONObject(i) ?: return@mapNotNull null
                    val t = o.optString("text")
                    if (t.isBlank()) null else Item(t, o.optLong("at", 0L))
                }
            }.getOrDefault(emptyList())
        }

        /**
         * "skrevet 21:14" / "skrevet i går 21:14" — så man kan bedømme om
         * beskeden stadig er den man vil sende. Uden tidspunkt er en kø-besked
         * bare tekst uden situation.
         *
         * [zone] er telefonens tidszone; tests giver en fast zone, så
         * etiketten (og screenshots) ikke afhænger af maskinens TZ.
         */
        fun writtenLabel(
            atMillis: Long,
            nowMillis: Long,
            zone: java.time.ZoneId = java.time.ZoneId.systemDefault(),
        ): String {
            if (atMillis <= 0L) return "skrevet tidligere"
            val at = java.time.Instant.ofEpochMilli(atMillis).atZone(zone)
            val today = java.time.Instant.ofEpochMilli(nowMillis).atZone(zone).toLocalDate()
            val time = at.format(java.time.format.DateTimeFormatter.ofPattern("HH:mm"))
            return when (at.toLocalDate()) {
                today -> "skrevet $time"
                // Kalenderdage, ikke dag-i-året: 31/12 er også "i går" den 1/1.
                today.minusDays(1) -> "skrevet i går $time"
                else -> "skrevet " + at.format(java.time.format.DateTimeFormatter.ofPattern("d/M HH:mm"))
            }
        }
    }
}
