package dk.ternedal.modelrig.desktop.net

import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

class CapabilityDescriptorV2FixtureTest {
    private val json = Json { ignoreUnknownKeys = false }

    private fun fixtureText(): String {
        val cwd = File(System.getProperty("user.dir"))
        val candidates = listOf(
            File(cwd, "../contracts/kaliv-capability-v2-fixtures.json"),
            File(cwd, "contracts/kaliv-capability-v2-fixtures.json"),
        )
        val file = candidates.firstOrNull { it.isFile }
            ?: error("shared capability fixtures not found from ${cwd.absolutePath}")
        return file.readText(Charsets.UTF_8)
    }

    @Test
    fun acceptsAndCanonicalizesEverySharedValidFixture() {
        val fixtures = json.parseToJsonElement(fixtureText()).jsonObject
        assertEquals(
            "kaliv-capability-fixtures/v1",
            fixtures.getValue("schema").jsonPrimitive.content,
        )
        val valid = fixtures.getValue("valid").jsonArray
        assertEquals(2, valid.size)

        var sawConfiguredService = false
        for (fixtureElement in valid) {
            val fixture = fixtureElement.jsonObject
            val descriptor = CapabilityDescriptorV2.parse(
                fixture.getValue("descriptor").toString(),
            )
            assertEquals(
                fixture.getValue("canonical").jsonPrimitive.content,
                descriptor.canonicalJson(),
            )
            assertEquals("kaliv-capability/v2", descriptor.schema)
            assertFalse(descriptor.productionActivation)
            if (descriptor.network.mode == "configured_service") {
                sawConfiguredService = true
                assertEquals(listOf("ollama"), descriptor.network.destinations)
            }
        }
        assertTrue(sawConfiguredService, "configured_service fixture was not exercised")
    }

    @Test
    fun rejectsEverySharedInvalidFixture() {
        val fixtures = json.parseToJsonElement(fixtureText()).jsonObject
        val invalid = fixtures.getValue("invalid").jsonArray
        assertEquals(16, invalid.size)
        for (fixtureElement in invalid) {
            val fixture = fixtureElement.jsonObject
            val name = fixture.getValue("name").jsonPrimitive.content
            assertFailsWith<CapabilityContractException>(
                message = "invalid fixture accepted: $name",
            ) {
                CapabilityDescriptorV2.parse(
                    fixture.getValue("descriptor").toString(),
                )
            }
        }
    }
}
