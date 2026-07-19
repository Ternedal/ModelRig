package dk.ternedal.modelrig.net

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class CapabilityDescriptorV2FixtureTest {
    private fun fixtureRoot(): JSONObject {
        val cwd = File(System.getProperty("user.dir"))
        val candidates = listOf(
            File(cwd, "../contracts/kaliv-capability-v2-fixtures.json"),
            File(cwd, "contracts/kaliv-capability-v2-fixtures.json"),
        )
        val file = candidates.firstOrNull { it.isFile }
            ?: error("shared capability fixtures not found from ${cwd.absolutePath}")
        return JSONObject(file.readText(Charsets.UTF_8))
    }

    @Test
    fun acceptsAndCanonicalizesEverySharedValidFixture() {
        val fixtures = fixtureRoot()
        assertEquals("kaliv-capability-fixtures/v1", fixtures.getString("schema"))
        val valid = fixtures.getJSONArray("valid")
        assertEquals(2, valid.length())

        var sawConfiguredService = false
        for (index in 0 until valid.length()) {
            val fixture = valid.getJSONObject(index)
            val descriptor = CapabilityDescriptorV2.parse(
                fixture.getJSONObject("descriptor"),
            )
            assertEquals(fixture.getString("canonical"), descriptor.canonicalJson())
            assertEquals("kaliv-capability/v2", descriptor.schema)
            assertFalse(descriptor.productionActivation)
            if (descriptor.network.mode == "configured_service") {
                sawConfiguredService = true
                assertEquals(listOf("ollama"), descriptor.network.destinations)
            }
        }
        assertTrue("configured_service fixture was not exercised", sawConfiguredService)
    }

    @Test
    fun rejectsEverySharedInvalidFixture() {
        val invalid = fixtureRoot().getJSONArray("invalid")
        assertEquals(16, invalid.length())
        for (index in 0 until invalid.length()) {
            val fixture = invalid.getJSONObject(index)
            val name = fixture.getString("name")
            try {
                CapabilityDescriptorV2.parse(fixture.getJSONObject("descriptor"))
                throw AssertionError("invalid fixture accepted: $name")
            } catch (_: CapabilityContractException) {
                // Expected: Android must fail on the same contract cases as worker/backend.
            }
        }
    }
}
