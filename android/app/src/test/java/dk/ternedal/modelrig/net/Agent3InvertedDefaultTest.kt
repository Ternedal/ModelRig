package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Den ene `true` blandt et dusin `false` er med vilje.
 *
 * Agent3ValidationClient og Agent3TaskReadinessClient laeser deres boolske
 * felter med `optBoolean(navn, false)` -- mangler feltet, er svaret "ikke klar".
 * Undtagen `production_activation`, som laeses med default **true**.
 *
 * Inversionen foelger af hvad feltet BETYDER. De oevrige er tilladelser: et
 * manglende felt maa ikke give adgang. `production_activation` er en fare: et
 * manglende felt maa ikke give tryghed. Begge defaults peger altsaa samme vej
 * -- mod at afvise -- selv om den ene er true og de andre false.
 *
 * Den her test findes fordi inversionen LIGNER en fejl. Den er den eneste true
 * i naerheden, og præcis den slags en oprydning retter "for konsistens". Goer
 * nogen det, bliver et fail-closed tjek til fail-open uden at noget andet
 * aendrer sig.
 */
class Agent3InvertedDefaultTest {

    private fun response(body: String) = MockResponse()
        .setHeader("Content-Type", "application/json").setBody(body)

    @Test
    fun aMissingProductionActivationIsTreatedAsActivated() {
        // Feltet udeladt HELT -- baade paa roden og i evidensen.
        val s = MockWebServer()
        s.enqueue(
            response(
                """{"enabled":true,"experimental":true,
                    "rig_validation":{"configured":true,"present":true}}""",
            ),
        )
        s.start()
        try {
            var refused = false
            try {
                Agent3ValidationClient(s.url("/").toString(), "t").status()
            } catch (e: ModelRigException) {
                refused = true
            }
            assertTrue(
                "et manglende production_activation skal laeses som AKTIVERET " +
                    "og afvises -- ikke som fravaerende og dermed ufarligt",
                refused,
            )
        } finally {
            s.shutdown()
        }
    }

    @Test
    fun anExplicitFalseIsAccepted() {
        // Kontrolpunkt. Uden det ville en klient der afviste ALT bestaa
        // testen ovenfor, og inversionen ville ikke vaere maalt.
        val s = MockWebServer()
        s.enqueue(
            response(
                """{"enabled":true,"experimental":true,"production_activation":false,
                    "rig_validation":{"production_activation":false,"configured":true,
                    "present":true,"structurally_valid":true,"fresh":true,
                    "version_match":true,"proofs":{}}}""",
            ),
        )
        s.start()
        try {
            val status = Agent3ValidationClient(s.url("/").toString(), "t").status()
            assertTrue("en eksplicit false skal accepteres", !status.productionActivation)
        } finally {
            s.shutdown()
        }
    }

    @Test
    fun activationInTheEvidenceAloneIsAlsoRefused() {
        // Roden siger false, evidensen siger true. Begge skal tjekkes -- ellers
        // kunne en rapport paastaa aktivering uden at nogen saa det.
        val s = MockWebServer()
        s.enqueue(
            response(
                """{"enabled":true,"experimental":true,"production_activation":false,
                    "rig_validation":{"production_activation":true,"configured":true}}""",
            ),
        )
        s.start()
        try {
            var refused = false
            try {
                Agent3ValidationClient(s.url("/").toString(), "t").status()
            } catch (e: ModelRigException) {
                refused = true
            }
            assertTrue("aktivering i evidensen alene skal ogsaa afvises", refused)
        } finally {
            s.shutdown()
        }
    }
}
