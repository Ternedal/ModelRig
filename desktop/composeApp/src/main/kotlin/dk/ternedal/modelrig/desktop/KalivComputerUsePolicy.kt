package dk.ternedal.modelrig.desktop

/**
 * Product-authoritative presentation for desktop computer-use while no live
 * execution/viewport contract is wired into this client.
 *
 * The worker may support browser-use independently; that does not authorize the
 * desktop UI to simulate a run or claim remote control. Until the desktop owns
 * real run state, viewport evidence and confirmation outcomes, every execution
 * affordance stays fail-closed.
 */
internal data class KalivComputerUsePresentation(
    val title: String,
    val detail: String,
    val executionEnabled: Boolean,
    val showLiveViewport: Boolean,
    val showApproval: Boolean,
    val claimsLiveControl: Boolean,
)

internal fun presentComputerUse(): KalivComputerUsePresentation =
    KalivComputerUsePresentation(
        title = "Computer-use er ikke tilgængelig endnu",
        detail = "Desktop er endnu ikke koblet til den rigtige browser-kørsel. " +
            "Kaliv viser derfor ikke en simuleret kørsel som om den var live.",
        executionEnabled = false,
        showLiveViewport = false,
        showApproval = false,
        claimsLiveControl = false,
    )
