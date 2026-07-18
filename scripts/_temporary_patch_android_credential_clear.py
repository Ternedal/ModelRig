from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected {label} exactly once in {path}, found {count}")
    path.write_text(text.replace(old, new), encoding="utf-8")


token_path = Path(
    "android/app/src/main/java/dk/ternedal/modelrig/data/TokenStore.kt"
)
replace_once(
    token_path,
    '''    fun clearRig() { prefs.edit().remove("token_enc").remove("token").remove("base_url").apply() }
    fun clearCloud() { prefs.edit().remove("cloud_key_enc").apply() }
    fun clear() { prefs.edit().clear().apply() }
''',
    '''    fun clearRig(): Boolean = CredentialPersistence.commit {
        prefs.edit().remove("token_enc").remove("token").remove("base_url").commit()
    }

    fun clearCloud(): Boolean = CredentialPersistence.commit {
        prefs.edit().remove("cloud_key_enc").commit()
    }

    fun clear(): Boolean = CredentialPersistence.commit {
        prefs.edit().clear().commit()
    }
''',
    "credential clear methods",
)


ui_path = Path(
    "android/app/src/main/java/dk/ternedal/modelrig/ui/AppUi.kt"
)
replace_once(
    ui_path,
    '''                    TextButton(onClick = { store.clearCloud(); configured = false; key = "" }) { Text("Ryd", color = KalivTheme.colors.danger) }
''',
    '''                    TextButton(
                        onClick = {
                            if (store.clearCloud()) {
                                configured = false
                                key = ""
                                msg = null
                            } else {
                                msg = "Cloud-adgangen kunne ikke ryddes sikkert."
                            }
                        },
                    ) { Text("Ryd", color = KalivTheme.colors.danger) }
''',
    "cloud clear UI",
)
replace_once(
    ui_path,
    '''                    TextButton(onClick = { store.clearRig(); connected = false; reachable = null }) { Text("Afbryd", color = KalivTheme.colors.danger) }
''',
    '''                    TextButton(
                        onClick = {
                            if (store.clearRig()) {
                                connected = false
                                reachable = null
                                msg = null
                            } else {
                                msg = "Rig-adgangen kunne ikke ryddes sikkert."
                            }
                        },
                    ) { Text("Afbryd", color = KalivTheme.colors.danger) }
''',
    "rig clear UI",
)


entry_path = Path(
    "android/app/src/main/java/dk/ternedal/modelrig/ui/AppEntryUi.kt"
)
replace_once(
    entry_path,
    '''            onClear = {
                if (initialSources.rig == CredentialCondition.INVALID) store.clearRig()
                if (initialSources.cloud == CredentialCondition.INVALID) store.clearCloud()
                continueToApp = true
            },
''',
    '''            onClear = {
                val rigCleared =
                    initialSources.rig != CredentialCondition.INVALID || store.clearRig()
                val cloudCleared =
                    initialSources.cloud != CredentialCondition.INVALID || store.clearCloud()
                val cleared = rigCleared && cloudCleared
                if (cleared) continueToApp = true
                cleared
            },
''',
    "recovery clear callback",
)
replace_once(
    entry_path,
    '''    onContinue: () -> Unit,
    onClear: () -> Unit,
) {
    val affected = when {
''',
    '''    onContinue: () -> Unit,
    onClear: () -> Boolean,
) {
    var clearFailed by remember { mutableStateOf(false) }
    val affected = when {
''',
    "recovery clear signature",
)
replace_once(
    entry_path,
    '''                    OutlinedButton(
                        onClick = onClear,
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text("Ryd gamle credentials")
                    }
''',
    '''                    OutlinedButton(
                        onClick = { clearFailed = !onClear() },
                        modifier = Modifier.fillMaxWidth(),
                    ) {
                        Text("Ryd gamle credentials")
                    }
                    if (clearFailed) {
                        Spacer(Modifier.height(8.dp))
                        Text(
                            "De gamle credentials kunne ikke ryddes. Prøv igen eller overskriv dem i opsætningen.",
                            color = KalivTheme.colors.danger,
                            fontSize = 12.sp,
                        )
                    }
''',
    "recovery clear button",
)


contract_path = Path("tests/android_credential_commit_contract.py")
text = contract_path.read_text(encoding="utf-8")
old = '''    "cloud setup uses the transactional boundary": "store.saveCloudConfiguration(" in ui,
    "UI branches on confirmed persistence": ui.count("if (saved)") >= 4,
'''
new = '''    "cloud setup uses the transactional boundary": "store.saveCloudConfiguration(" in ui,
    "credential clears return confirmed results": "fun clearRig(): Boolean" in store and "fun clearCloud(): Boolean" in store,
    "setup clear buttons branch on commit results": "if (store.clearRig())" in ui and "if (store.clearCloud())" in ui,
    "UI branches on confirmed persistence": ui.count("if (saved)") >= 4,
'''
if text.count(old) != 1:
    raise SystemExit(f"expected contract checks exactly once, found {text.count(old)}")
contract_path.write_text(text.replace(old, new), encoding="utf-8")
