package dk.ternedal.modelrig.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.accessibility.enableAccessibilityChecks
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.tryPerformAccessibilityChecks
import androidx.compose.ui.unit.dp
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.filters.SdkSuppress
import dk.ternedal.modelrig.net.ControlCenterAuditEntry
import dk.ternedal.modelrig.net.ControlCenterAuditEvidence
import dk.ternedal.modelrig.net.ControlCenterAuditSnapshot
import dk.ternedal.modelrig.net.ControlCenterCommonDataSharing
import dk.ternedal.modelrig.net.ControlCenterGitHubAuditEntry
import dk.ternedal.modelrig.net.ControlCenterGitHubConnectorSnapshot
import dk.ternedal.modelrig.net.ControlCenterGitHubGrant
import dk.ternedal.modelrig.net.ControlCenterPrivacy
import dk.ternedal.modelrig.net.ControlCenterScopedPermissions
import dk.ternedal.modelrig.net.ControlCenterToolResultEgress
import dk.ternedal.modelrig.ui.theme.KalivTheme
import dk.ternedal.modelrig.ui.theme.ModelRigTheme
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
@SdkSuppress(minSdkVersion = 34)
class ControlCenterAccessibilityInstrumentedTest {
    @get:Rule
    val composeTestRule = createComposeRule()

    @Test
    fun privacySectionHasReadableSemanticsAndPassesAccessibilityChecks() {
        composeTestRule.setContent {
            ModelRigTheme(dark = true) {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = KalivTheme.colors.background,
                ) {
                    Column(
                        modifier = Modifier
                            .verticalScroll(rememberScrollState())
                            .padding(24.dp),
                    ) {
                        ControlCenterPrivacySection(privacy(privateGateEnabled = false))
                    }
                }
            }
        }

        composeTestRule.onNodeWithText("Privacy & data-sharing").assertIsDisplayed()
        composeTestRule.onNodeWithText(
            "Privat cloud-data: tilladt i legacy-mode · egress-gaten er slået fra",
        ).assertIsDisplayed()
        composeTestRule.onNodeWithText("Hemmelig data: altid forbudt").assertIsDisplayed()

        composeTestRule.enableAccessibilityChecks()
        composeTestRule.onRoot().tryPerformAccessibilityChecks()
    }

    @Test
    fun auditFiltersExposeLabelsAndPassAccessibilityChecksInLightMode() {
        val snapshot = ControlCenterAuditSnapshot(
            entries = listOf(
                ControlCenterAuditEntry(
                    timestamp = "2026-08-11T13:00:00Z",
                    taskRef = "task-123",
                    capabilityId = "tool:note_append",
                    tool = "note_append",
                    connectorId = null,
                    approvalId = "approval-123",
                    risk = "write",
                    outcome = "executed",
                    origin = "local",
                    durationMs = 12,
                ),
            ),
            connectorEvidence = ControlCenterAuditEvidence(
                state = "unavailable",
                reason = "tool_audit_does_not_record_connector_id",
            ),
        )

        composeTestRule.setContent {
            ModelRigTheme(dark = false) {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = KalivTheme.colors.background,
                ) {
                    Column(
                        modifier = Modifier
                            .verticalScroll(rememberScrollState())
                            .padding(24.dp),
                    ) {
                        ControlCenterAuditSection(
                            snapshot = snapshot,
                            error = null,
                            loading = false,
                        )
                    }
                }
            }
        }

        composeTestRule.onNodeWithText("Audit").assertIsDisplayed()
        composeTestRule.onNodeWithText("Task / conversation-ref").assertIsDisplayed()
        composeTestRule.onNodeWithText("Capability").assertIsDisplayed()
        composeTestRule.onNodeWithText("Approval").assertIsDisplayed()

        composeTestRule.enableAccessibilityChecks()
        composeTestRule.onRoot().tryPerformAccessibilityChecks()
    }

    @Test
    fun githubConnectorGrantsFiltersAndRevokeControlPassAccessibilityChecks() {
        val snapshot = ControlCenterGitHubConnectorSnapshot(
            grants = listOf(
                ControlCenterGitHubGrant(
                    grantId = "ghg_0123456789abcdef0123456789abcdef",
                    account = "ternedal",
                    repositories = listOf("ternedal/modelrig"),
                    operations = listOf("issue", "pull_request"),
                    scopeSha256 = "a".repeat(64),
                    createdAt = "2026-08-12T09:00:00Z",
                    createdBy = "loopback-operator",
                    status = "active",
                    revokedAt = null,
                    revokedBy = null,
                ),
            ),
            audit = listOf(
                ControlCenterGitHubAuditEntry(
                    timestamp = "2026-08-12T09:15:00Z",
                    account = "ternedal",
                    repository = "ternedal/modelrig",
                    operation = "issue",
                    objectId = "88",
                    outcome = "executed",
                    grantId = "ghg_0123456789abcdef0123456789abcdef",
                    scopeSha256 = "a".repeat(64),
                    revision = "abc123",
                    durationMs = 12,
                    detail = "fresh_remote_read",
                ),
            ),
        )

        composeTestRule.setContent {
            ModelRigTheme(dark = true) {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = KalivTheme.colors.background,
                ) {
                    Column(
                        modifier = Modifier
                            .verticalScroll(rememberScrollState())
                            .padding(24.dp),
                    ) {
                        ControlCenterGitHubConnectorSection(
                            snapshot = snapshot,
                            loading = false,
                            error = null,
                            mutationError = null,
                            revokingId = null,
                            onRevoke = {},
                        )
                    }
                }
            }
        }

        composeTestRule.onNodeWithText("GitHub connector").assertIsDisplayed()
        composeTestRule.onNodeWithText("Ekstern konto: GitHub · ternedal").assertIsDisplayed()
        composeTestRule.onNodeWithText(controlCenterGitHubOutboundDataLabel()).assertIsDisplayed()
        composeTestRule.onNodeWithText("Tilbagekald tilladelse").assertIsDisplayed()
        composeTestRule.onNodeWithText("Connector").assertIsDisplayed()
        composeTestRule.onNodeWithText("Repository").assertIsDisplayed()
        composeTestRule.onNodeWithText("Operation").assertIsDisplayed()
        composeTestRule.onNodeWithText("Udfald").assertIsDisplayed()

        composeTestRule.enableAccessibilityChecks()
        composeTestRule.onRoot().tryPerformAccessibilityChecks()
    }

    private fun privacy(privateGateEnabled: Boolean) = ControlCenterPrivacy(
        schema = "kaliv-control-center-privacy/v1",
        evidenceState = "ready",
        reason = null,
        toolResultEgress = ControlCenterToolResultEgress(
            privateGateEnabled = privateGateEnabled,
            publicRule = "allowed",
            operationalRule = "allowed",
            privateRule = if (privateGateEnabled) {
                "blocked_requires_explicit_consent"
            } else {
                "allowed_legacy_mode"
            },
            secretRule = "forbidden",
        ),
        commonDataSharing = ControlCenterCommonDataSharing(
            state = "dormant",
            runtimeIntegrated = false,
            reason = "common_data_sharing_not_runtime_integrated",
        ),
        scopedPermissions = ControlCenterScopedPermissions(
            state = "unavailable",
            revocationSupported = false,
            reason = "no_active_scoped_permission_authority",
        ),
        productionActivation = false,
    )
}
