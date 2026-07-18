from pathlib import Path


path = Path("android/app/src/main/java/dk/ternedal/modelrig/ui/AppUi.kt")
text = path.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    text = text.replace(old, new, 1)


replace_once(
    '''onClick = {
                        runCatching {
                            if (key.isNotBlank()) store.cloudKey = key.trim()
                            store.cloudModel = model.trim().ifBlank { "gpt-oss:120b" }
                            store.chatMode = "cloud"
                        }.onSuccess { key = ""; configured = true; msg = null; onSaved() }
                            .onFailure { msg = "Kunne ikke gemme nøgle: ${it.message}" }
                    },''',
    '''onClick = {
                        val requestedKey = key.trim()
                        val credentialSaved =
                            requestedKey.isBlank() || store.saveCloudCredential(requestedKey)
                        if (credentialSaved) {
                            store.cloudModel = model.trim().ifBlank { "gpt-oss:120b" }
                            store.chatMode = "cloud"
                            key = ""
                            configured = store.hasCloud
                            msg = null
                            onSaved()
                        } else {
                            msg = "Kunne ikke gemme cloud-adgangen. Prøv igen."
                        }
                    },''',
    "cloud save callback",
)

replace_once(
    '''TextButton(onClick = { store.clearCloud(); configured = false; key = "" }) { Text("Ryd", color = KalivTheme.colors.danger) }''',
    '''TextButton(onClick = {
                        if (store.clearCloud()) {
                            configured = false
                            key = ""
                            msg = null
                        } else {
                            msg = "Kunne ikke rydde cloud-adgangen. Prøv igen."
                        }
                    }) { Text("Ryd", color = KalivTheme.colors.danger) }''',
    "cloud clear callback",
)

replace_once(
    '''onApply = { profile ->
                    store.baseUrl = profile.serverUrl
                    store.token = profile.deviceToken
                    store.chatMode = "rig"
                    baseUrl = profile.serverUrl
                    connected = true
                    onConnected()
                },''',
    '''onApply = { profile ->
                    if (store.saveRigCredential(profile.deviceToken)) {
                        store.baseUrl = profile.serverUrl
                        store.chatMode = "rig"
                        baseUrl = profile.serverUrl
                        connected = true
                        msg = null
                        onConnected()
                    } else {
                        msg = "Kunne ikke gemme rig-adgangen. Prøv igen."
                    }
                },''',
    "rig profile callback",
)

replace_once(
    '''res.onSuccess {
                                    store.baseUrl = url; store.token = it; store.chatMode = "rig"
                                    busy = false; connected = true; reachable = true; onConnected()
                                }.onFailure { msg = it.message ?: "Kunne ikke forbinde"; busy = false }''',
    '''res.onSuccess { claimedToken ->
                                    if (store.saveRigCredential(claimedToken)) {
                                        store.baseUrl = url; store.chatMode = "rig"
                                        busy = false; connected = true; reachable = true; msg = null; onConnected()
                                    } else {
                                        msg = "Parringen lykkedes, men rig-adgangen kunne ikke gemmes. Prøv igen."
                                        busy = false
                                    }
                                }.onFailure {
                                    msg = "Kunne ikke forbinde til rig'en. Kontrollér URL og parringskode."
                                    busy = false
                                }''',
    "pairing callback",
)

replace_once(
    '''TextButton(onClick = { store.clearRig(); connected = false; reachable = null }) { Text("Afbryd", color = KalivTheme.colors.danger) }''',
    '''TextButton(onClick = {
                        if (store.clearRig()) {
                            connected = false
                            reachable = null
                            msg = null
                        } else {
                            msg = "Kunne ikke rydde rig-adgangen. Prøv igen."
                        }
                    }) { Text("Afbryd", color = KalivTheme.colors.danger) }''',
    "rig clear callback",
)

path.write_text(text, encoding="utf-8")
