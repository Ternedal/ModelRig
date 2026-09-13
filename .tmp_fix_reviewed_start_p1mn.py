from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one anchor, found {count}: {old[:80]!r}")
    write(path, text.replace(old, new, 1))


# ---------------------------------------------------------------------------
# P1m: backup/restore must carry the independent execution watermark sidecar.
# ---------------------------------------------------------------------------
core = "worker/app/agent3/core.py"
replace_once(
    core,
    "class AgentRunStore:\n",
    '''def agent3_execution_progress_path(path: str) -> str:\n    \"\"\"Return the independent monotonic execution-authority SQLite path.\"\"\"\n    return \":memory:\" if path == \":memory:\" else f\"{path}.execution-progress\"\n\n\nclass AgentRunStore:\n''',
)
replace_once(
    core,
    '        progress_path = ":memory:" if path == ":memory:" else f"{path}.execution-progress"\n',
    '        progress_path = agent3_execution_progress_path(path)\n',
)

backup = "worker/app/backup.py"
replace_once(
    backup,
    "  agent3-*.db                  Agent 3 runs/reviews/replans/memory/plans/approvals\n",
    "  agent3-*.db                  Agent 3 runs/reviews/replans/memory/plans/approvals\n  agent3-execution-progress.db   monotonic Agent 3 execution-start authority\n",
)
replace_once(
    backup,
    "Schema 1 is the original V7 inventory. Schema 2 is the current 2.x inventory.\nNew code accepts both so old backups remain restorable; new archives use schema\n2 so old code fails closed instead of accepting an archive whose newer keys it\nwould silently skip.\n",
    "Schema 1 is the original V7 inventory. Schema 2 expanded the 2.x inventory.\nSchema 3 binds Agent 3 run state to its independent monotonic execution-progress\nsidecar. Older schemas remain parseable, but any archive containing only one half\nof that authority pair is invalid and restore fails closed. New archives use\nschema 3 so old code cannot silently skip the newer authority key.\n",
)
replace_once(backup, "BACKUP_SCHEMA = 2\nSUPPORTED_BACKUP_SCHEMAS = frozenset({1, BACKUP_SCHEMA})\n", "BACKUP_SCHEMA = 3\nSUPPORTED_BACKUP_SCHEMAS = frozenset({1, 2, BACKUP_SCHEMA})\n")
replace_once(
    backup,
    "from . import tools as _tools  # noqa: E402\n",
    "from . import tools as _tools  # noqa: E402\nfrom .agent3.core import agent3_execution_progress_path  # noqa: E402\n",
)
replace_once(
    backup,
    "@dataclass\nclass Item:\n",
    '''AGENT3_RUNS_KEY = "agent3-runs.db"\nAGENT3_EXECUTION_PROGRESS_KEY = "agent3-execution-progress.db"\n\n\ndef _agent3_authority_pair_problem(keys: set[str]) -> str | None:\n    has_runs = AGENT3_RUNS_KEY in keys\n    has_progress = AGENT3_EXECUTION_PROGRESS_KEY in keys\n    if has_runs == has_progress:\n        return None\n    missing = AGENT3_EXECUTION_PROGRESS_KEY if has_runs else AGENT3_RUNS_KEY\n    return (\n        "Agent 3 run state and monotonic execution-progress authority must be "\n        f"backed up/restored together; missing {missing}"\n    )\n\n\n@dataclass\nclass Item:\n''',
)
replace_once(
    backup,
    '''    out = [Item(key, _resolved(default, env), "file", required=False) for key, default, env in files]\n    out.insert(1, Item("data.json", _backend_data(), "file", required=False))\n''',
    '''    out = [Item(key, _resolved(default, env), "file", required=False) for key, default, env in files]\n    run_index = next(i for i, item in enumerate(out) if item.key == AGENT3_RUNS_KEY)\n    out.insert(\n        run_index + 1,\n        Item(\n            AGENT3_EXECUTION_PROGRESS_KEY,\n            agent3_execution_progress_path(out[run_index].path),\n            "file",\n            required=False,\n        ),\n    )\n    out.insert(1, Item("data.json", _backend_data(), "file", required=False))\n''',
)
replace_once(
    backup,
    '''    tmp = archive + ".tmp"\n    with tarfile.open(tmp, "w:gz") as tar:\n        for it in items():\n''',
    '''    inventory = items()\n    live_file_keys = {\n        it.key for it in inventory if it.kind == "file" and os.path.exists(it.path)\n    }\n    pair_problem = _agent3_authority_pair_problem(live_file_keys)\n    if pair_problem:\n        raise ValueError(f"refusing unsafe backup: {pair_problem}")\n\n    tmp = archive + ".tmp"\n    with tarfile.open(tmp, "w:gz") as tar:\n        for it in inventory:\n''',
)
replace_once(
    backup,
    '''    problems: list[str] = []\n    checked = 0\n''',
    '''    problems: list[str] = []\n    pair_problem = _agent3_authority_pair_problem(set(manifest["files"]))\n    if pair_problem:\n        problems.append(pair_problem)\n    checked = 0\n''',
)

backup_test = "tests/worker_backup.py"
replace_once(backup_test, '        if it.path.lower().endswith(".db"):\n', '        if it.key.endswith(".db"):\n')
replace_once(
    backup_test,
    '    "agent3-runs.db",\n',
    '    "agent3-runs.db",\n    "agent3-execution-progress.db",\n',
)
replace_once(
    backup_test,
    '''check(\n    next(it for it in backup.items() if it.key == "data.json").path == os.environ["MODELRIG_DATA"],\n    "inventory: backend pairing state follows MODELRIG_DATA",\n)\n''',
    '''check(\n    next(it for it in backup.items() if it.key == "data.json").path == os.environ["MODELRIG_DATA"],\n    "inventory: backend pairing state follows MODELRIG_DATA",\n)\nruns_path = next(it.path for it in backup.items() if it.key == "agent3-runs.db")\nprogress_path = next(\n    it.path for it in backup.items() if it.key == "agent3-execution-progress.db"\n)\ncheck(\n    progress_path == backup.agent3_execution_progress_path(runs_path),\n    "inventory: execution-progress authority follows the exact Agent3 run DB path",\n)\n''',
)
replace_once(backup_test, 'check(manifest["schema"] == 2, "schema: expanded 2.x inventory writes schema 2")\ncheck(1 in backup.SUPPORTED_BACKUP_SCHEMAS, "schema: current code retains schema-1 restore compatibility")\n', 'check(manifest["schema"] == 3, "schema: execution-authority inventory writes schema 3")\ncheck({1, 2} <= backup.SUPPORTED_BACKUP_SCHEMAS, "schema: current code still parses schema 1 and 2")\n')
replace_once(
    backup_test,
    '''def archive_with_schema(source: str, destination: str, schema: int) -> None:\n    """Copy an archive while changing only manifest.schema."""\n    with tarfile.open(source, "r:gz") as src, tarfile.open(destination, "w:gz") as dst:\n        for member in src.getmembers():\n            extracted = src.extractfile(member)\n            data = extracted.read() if extracted else b""\n            if member.name == "manifest.json":\n                manifest = json.loads(data)\n                manifest["schema"] = schema\n                data = json.dumps(manifest, indent=2, sort_keys=True).encode()\n            replacement = tarfile.TarInfo(member.name)\n            replacement.size = len(data)\n            dst.addfile(replacement, io.BytesIO(data))\n\n\n''',
    '''def archive_with_schema(source: str, destination: str, schema: int) -> None:\n    """Copy an archive while changing only manifest.schema."""\n    with tarfile.open(source, "r:gz") as src, tarfile.open(destination, "w:gz") as dst:\n        for member in src.getmembers():\n            extracted = src.extractfile(member)\n            data = extracted.read() if extracted else b""\n            if member.name == "manifest.json":\n                manifest = json.loads(data)\n                manifest["schema"] = schema\n                data = json.dumps(manifest, indent=2, sort_keys=True).encode()\n            replacement = tarfile.TarInfo(member.name)\n            replacement.size = len(data)\n            dst.addfile(replacement, io.BytesIO(data))\n\n\ndef archive_without_key(\n    source: str, destination: str, *, schema: int, omitted_key: str\n) -> None:\n    """Build a cryptographically coherent legacy archive missing one inventory key."""\n    omitted_member = f"data/{omitted_key}"\n    with tarfile.open(source, "r:gz") as src, tarfile.open(destination, "w:gz") as dst:\n        for member in src.getmembers():\n            if member.name == omitted_member:\n                continue\n            extracted = src.extractfile(member)\n            data = extracted.read() if extracted else b""\n            if member.name == "manifest.json":\n                manifest = json.loads(data)\n                manifest["schema"] = schema\n                manifest["files"].pop(omitted_key, None)\n                data = json.dumps(manifest, indent=2, sort_keys=True).encode()\n            replacement = tarfile.TarInfo(member.name)\n            replacement.size = len(data)\n            dst.addfile(replacement, io.BytesIO(data))\n\n\n''',
)
replace_once(
    backup_test,
    '''except ValueError:\n    check(True, "schema: unknown future schema is refused")\n\nwipe()\n''',
    '''except ValueError:\n    check(True, "schema: unknown future schema is refused")\n\nunsafe_legacy = os.path.join(_root, "unsafe-schema-2-without-execution-progress.tar.gz")\narchive_without_key(\n    archive,\n    unsafe_legacy,\n    schema=2,\n    omitted_key="agent3-execution-progress.db",\n)\nunsafe_check = backup.verify(unsafe_legacy)\ncheck(\n    not unsafe_check["ok"]\n    and any("execution-progress" in problem for problem in unsafe_check["problems"]),\n    "schema: Agent3 runs without monotonic execution authority fail verification",\n)\ntry:\n    backup.restore(unsafe_legacy, force=True)\n    check(False, "restore: legacy Agent3 runs without execution authority are refused")\nexcept ValueError:\n    check(True, "restore: legacy Agent3 runs without execution authority are refused")\n\nwipe()\n''',
)
replace_once(
    backup_test,
    '    if it.kind != "file" or not it.path.lower().endswith(".db"):\n',
    '    if it.kind != "file" or not it.key.endswith(".db"):\n',
)
replace_once(backup_test, 'check(backup._read_manifest(empty)["schema"] == 2, "create: empty rig still emits current schema 2")\n', 'check(backup._read_manifest(empty)["schema"] == 3, "create: empty rig still emits current schema 3")\n')

# ---------------------------------------------------------------------------
# P1n: clear callbacks must carry the exact reservation generation/envelope.
# ---------------------------------------------------------------------------
desktop_store = r'''package dk.ternedal.modelrig.desktop.data

import dk.ternedal.modelrig.desktop.Agent3DevConnectionBinding
import java.util.UUID

/** Exact durable slot identity captured by one reviewed-Start operation. */
data class Agent3ReviewedStartRecoveryReservation internal constructor(
    val encodedAuthority: String,
    internal val storageKey: String,
    internal val expectedEnvelope: String,
)

/** Separate URL-scoped persistence for reviewed Start; task-surface authority is never reused. */
class Agent3ReviewedStartRecoveryStore(
    private val db: DesktopChatDb,
    private val credentialTokenProvider: (() -> String?)? = null,
) {
    fun read(baseUrl: String?): String? {
        val key = agent3ReviewedStartRecoveryStorageKey(baseUrl) ?: return null
        val raw = db.getSetting(key)?.trim()?.takeIf { it.isNotEmpty() } ?: return null
        val bound = decodeBoundAuthority(raw) ?: return UNRESOLVED_CREDENTIAL_BINDING
        val currentFingerprint = currentCredentialFingerprint(baseUrl)
            ?: return UNRESOLVED_CREDENTIAL_BINDING
        if (currentFingerprint != bound.credentialFingerprint) return UNRESOLVED_CREDENTIAL_BINDING
        return bound.encodedAuthority
    }

    /** Read the current valid slot together with the exact generation that owns clearing authority. */
    fun readReservation(baseUrl: String?): Agent3ReviewedStartRecoveryReservation? {
        val key = agent3ReviewedStartRecoveryStorageKey(baseUrl) ?: return null
        val raw = db.getSetting(key)?.trim()?.takeIf { it.isNotEmpty() } ?: return null
        val bound = decodeBoundAuthority(raw) ?: return null
        val currentFingerprint = currentCredentialFingerprint(baseUrl) ?: return null
        if (currentFingerprint != bound.credentialFingerprint) return null
        return Agent3ReviewedStartRecoveryReservation(bound.encodedAuthority, key, raw)
    }

    /** Reserve an empty rig-scoped slot and return the exact generation-specific clear handle. */
    fun reserve(
        baseUrl: String?,
        encodedAuthority: String?,
    ): Agent3ReviewedStartRecoveryReservation? {
        val key = agent3ReviewedStartRecoveryStorageKey(baseUrl) ?: return null
        val authority = encodedAuthority?.trim()?.takeIf { it.isNotEmpty() } ?: return null
        val fingerprint = currentCredentialFingerprint(baseUrl) ?: return null
        val reservationGeneration = UUID.randomUUID().toString()
        val boundEnvelope = encodeBoundAuthority(fingerprint, reservationGeneration, authority)
        val saved = runCatching { db.putRawSettingIfAbsent(key, boundEnvelope) }.getOrDefault(false)
        return if (saved) {
            Agent3ReviewedStartRecoveryReservation(authority, key, boundEnvelope)
        } else {
            null
        }
    }

    /** Clear only the exact rig + credential + generation captured by this operation. */
    fun clearIfMatches(
        baseUrl: String?,
        reservation: Agent3ReviewedStartRecoveryReservation,
    ): Boolean {
        val key = agent3ReviewedStartRecoveryStorageKey(baseUrl) ?: return false
        if (reservation.storageKey != key) return false
        return runCatching {
            db.removeRawSettingIfValue(key, reservation.expectedEnvelope)
        }.getOrDefault(false)
    }

    private fun currentCredentialFingerprint(baseUrl: String?): String? {
        Agent3DevConnectionBinding.recentCredentialFingerprint(baseUrl)?.let { return it }
        val persistedToken = runCatching {
            credentialTokenProvider?.invoke()
                ?: System.getenv("MODELRIG_TOKEN")?.takeIf { it.isNotBlank() }
                ?: db.getSetting("deviceToken")
        }.getOrNull()
        return Agent3DevConnectionBinding.credentialFingerprint(baseUrl, persistedToken)
    }
}

internal fun agent3ReviewedStartRecoveryStorageKey(baseUrl: String?): String? =
    baseUrl
        ?.trim()
        ?.trimEnd('/')
        ?.takeIf { it.isNotEmpty() }
        ?.let { "$REVIEWED_START_RECOVERY_KEY_PREFIX:$it" }

private data class CredentialBoundAuthority(
    val credentialFingerprint: String,
    val reservationGeneration: String,
    val encodedAuthority: String,
)

private fun encodeBoundAuthority(
    fingerprint: String,
    reservationGeneration: String,
    authority: String,
): String = "$RECOVERY_STORAGE_SCHEMA\n$fingerprint\n$reservationGeneration\n$authority"

private fun decodeBoundAuthority(raw: String): CredentialBoundAuthority? {
    val firstBreak = raw.indexOf('\n')
    if (firstBreak <= 0 || raw.substring(0, firstBreak) != RECOVERY_STORAGE_SCHEMA) return null
    val secondBreak = raw.indexOf('\n', firstBreak + 1)
    if (secondBreak <= firstBreak + 1) return null
    val thirdBreak = raw.indexOf('\n', secondBreak + 1)
    if (thirdBreak <= secondBreak + 1) return null
    val fingerprint = raw.substring(firstBreak + 1, secondBreak)
    if (!SHA256.matches(fingerprint)) return null
    val reservationGeneration = raw.substring(secondBreak + 1, thirdBreak)
    if (!UUID_LOWERCASE.matches(reservationGeneration)) return null
    val authority = raw.substring(thirdBreak + 1).trim().takeIf { it.isNotEmpty() } ?: return null
    return CredentialBoundAuthority(fingerprint, reservationGeneration, authority)
}

private const val REVIEWED_START_RECOVERY_KEY_PREFIX = "agent3ReviewedStartRecovery"
private const val RECOVERY_STORAGE_SCHEMA = "kaliv-agent3-reviewed-start-storage/v3"
private const val UNRESOLVED_CREDENTIAL_BINDING = "kaliv-agent3-reviewed-start-unresolved-credential-binding"
private val SHA256 = Regex("^[0-9a-f]{64}$")
private val UUID_LOWERCASE = Regex("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
'''
write("desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/data/Agent3ReviewedStartRecoveryStore.kt", desktop_store)

android_store = r'''package dk.ternedal.modelrig.data

import android.content.Context
import dk.ternedal.modelrig.logic.Agent3ReviewConnectionBinding
import java.util.UUID

/** Exact durable slot identity captured by one reviewed-Start operation. */
data class Agent3ReviewedStartRecoveryReservation internal constructor(
    val encodedAuthority: String,
    internal val storageKey: String,
    internal val expectedEnvelope: String,
)

/** URL-scoped storage for the opaque reviewed-Start recovery authority record. */
class Agent3ReviewedStartRecoveryStore(
    context: Context,
    private val credentialTokenProvider: (() -> String?)? = null,
) {
    private val appContext = context.applicationContext
    private val prefs = appContext.getSharedPreferences("modelrig", Context.MODE_PRIVATE)

    fun read(baseUrl: String?): String? {
        val key = agent3ReviewedStartRecoveryStorageKey(baseUrl) ?: return null
        val raw = prefs.getString(key, null)?.trim()?.takeIf { it.isNotEmpty() } ?: return null
        val bound = decodeBoundAuthority(raw) ?: return UNRESOLVED_CREDENTIAL_BINDING
        val currentFingerprint = currentCredentialFingerprint(baseUrl)
            ?: return UNRESOLVED_CREDENTIAL_BINDING
        if (currentFingerprint != bound.credentialFingerprint) return UNRESOLVED_CREDENTIAL_BINDING
        return bound.encodedAuthority
    }

    /** Read the current valid slot together with the exact generation that owns clearing authority. */
    fun readReservation(baseUrl: String?): Agent3ReviewedStartRecoveryReservation? {
        val key = agent3ReviewedStartRecoveryStorageKey(baseUrl) ?: return null
        synchronized(slotLock) {
            val raw = prefs.getString(key, null)?.trim()?.takeIf { it.isNotEmpty() } ?: return null
            val bound = decodeBoundAuthority(raw) ?: return null
            val currentFingerprint = currentCredentialFingerprint(baseUrl) ?: return null
            if (currentFingerprint != bound.credentialFingerprint) return null
            return Agent3ReviewedStartRecoveryReservation(bound.encodedAuthority, key, raw)
        }
    }

    /** Reserve an empty slot atomically across concurrent screen/store instances. */
    fun reserve(
        baseUrl: String?,
        encodedAuthority: String?,
    ): Agent3ReviewedStartRecoveryReservation? {
        val key = agent3ReviewedStartRecoveryStorageKey(baseUrl) ?: return null
        val authority = encodedAuthority?.trim()?.takeIf { it.isNotEmpty() } ?: return null
        val fingerprint = currentCredentialFingerprint(baseUrl) ?: return null
        val reservationGeneration = UUID.randomUUID().toString()
        val boundEnvelope = encodeBoundAuthority(fingerprint, reservationGeneration, authority)
        synchronized(slotLock) {
            val current = prefs.getString(key, null)?.trim()?.takeIf { it.isNotEmpty() }
            if (current != null) return null
            val saved = prefs.edit().putString(key, boundEnvelope).commit()
            return if (saved) {
                Agent3ReviewedStartRecoveryReservation(authority, key, boundEnvelope)
            } else {
                null
            }
        }
    }

    /** Clear only the exact rig + credential + generation captured by this operation. */
    fun clearIfMatches(
        baseUrl: String?,
        reservation: Agent3ReviewedStartRecoveryReservation,
    ): Boolean {
        val key = agent3ReviewedStartRecoveryStorageKey(baseUrl) ?: return false
        if (reservation.storageKey != key) return false
        synchronized(slotLock) {
            val current = prefs.getString(key, null)?.trim()?.takeIf { it.isNotEmpty() }
            if (current != reservation.expectedEnvelope) return false
            return prefs.edit().remove(key).commit()
        }
    }

    private fun currentCredentialFingerprint(baseUrl: String?): String? {
        val persistedToken = runCatching {
            credentialTokenProvider?.invoke() ?: TokenStore(appContext).token
        }.getOrNull()
        return Agent3ReviewConnectionBinding.credentialFingerprint(baseUrl, persistedToken)
    }

    private companion object {
        val slotLock = Any()
    }
}

internal fun agent3ReviewedStartRecoveryStorageKey(baseUrl: String?): String? =
    baseUrl
        ?.trim()
        ?.trimEnd('/')
        ?.takeIf { it.isNotEmpty() }
        ?.let { "$REVIEWED_START_RECOVERY_KEY_PREFIX:$it" }

private data class CredentialBoundAuthority(
    val credentialFingerprint: String,
    val reservationGeneration: String,
    val encodedAuthority: String,
)

private fun encodeBoundAuthority(
    fingerprint: String,
    reservationGeneration: String,
    authority: String,
): String = "$RECOVERY_STORAGE_SCHEMA\n$fingerprint\n$reservationGeneration\n$authority"

private fun decodeBoundAuthority(raw: String): CredentialBoundAuthority? {
    val firstBreak = raw.indexOf('\n')
    if (firstBreak <= 0 || raw.substring(0, firstBreak) != RECOVERY_STORAGE_SCHEMA) return null
    val secondBreak = raw.indexOf('\n', firstBreak + 1)
    if (secondBreak <= firstBreak + 1) return null
    val thirdBreak = raw.indexOf('\n', secondBreak + 1)
    if (thirdBreak <= secondBreak + 1) return null
    val fingerprint = raw.substring(firstBreak + 1, secondBreak)
    if (!SHA256.matches(fingerprint)) return null
    val reservationGeneration = raw.substring(secondBreak + 1, thirdBreak)
    if (!UUID_LOWERCASE.matches(reservationGeneration)) return null
    val authority = raw.substring(thirdBreak + 1).trim().takeIf { it.isNotEmpty() } ?: return null
    return CredentialBoundAuthority(fingerprint, reservationGeneration, authority)
}

private const val REVIEWED_START_RECOVERY_KEY_PREFIX = "agent3_reviewed_start_recovery"
private const val RECOVERY_STORAGE_SCHEMA = "kaliv-agent3-reviewed-start-storage/v3"
private const val UNRESOLVED_CREDENTIAL_BINDING = "kaliv-agent3-reviewed-start-unresolved-credential-binding"
private val SHA256 = Regex("^[0-9a-f]{64}$")
private val UUID_LOWERCASE = Regex("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
'''
write("android/app/src/main/java/dk/ternedal/modelrig/data/Agent3ReviewedStartRecoveryStore.kt", android_store)

# Wire exact reservation handles through the two UI callbacks.
android_ui = "android/app/src/main/java/dk/ternedal/modelrig/ui/Agent3ReviewScreen.kt"
replace_once(
    android_ui,
    "import dk.ternedal.modelrig.data.Agent3ReviewedStartRecoveryStore\n",
    "import dk.ternedal.modelrig.data.Agent3ReviewedStartRecoveryReservation\nimport dk.ternedal.modelrig.data.Agent3ReviewedStartRecoveryStore\n",
)
text = read(android_ui)
text = text.replace(
    "        authority: Agent3ReviewedStartRecoveryAuthority,\n    ) {",
    "        authority: Agent3ReviewedStartRecoveryAuthority,\n        reservation: Agent3ReviewedStartRecoveryReservation,\n    ) {",
)
if text.count("reservation: Agent3ReviewedStartRecoveryReservation") != 2:
    raise SystemExit("android UI: expected two reservation callback parameters")
text = text.replace(
    "recoveryStore.clearIfMatches(connection.baseUrl, authority.encode())",
    "recoveryStore.clearIfMatches(connection.baseUrl, reservation)",
)
if "clearIfMatches(connection.baseUrl, authority.encode())" in text:
    raise SystemExit("android UI: stale authority-only clear remains")
old = '''        val raw = recoveryStore.read(connection.baseUrl)\n        val authority = Agent3ReviewedStartRecoveryAuthority.decode(raw)\n        if (authority == null) {\n'''
new = '''        val reservation = recoveryStore.readReservation(connection.baseUrl)\n        val raw = reservation?.encodedAuthority ?: recoveryStore.read(connection.baseUrl)\n        val authority = Agent3ReviewedStartRecoveryAuthority.decode(raw)\n        if (authority == null || reservation == null) {\n'''
if text.count(old) != 1:
    raise SystemExit("android UI: recovery read anchor drift")
text = text.replace(old, new, 1)
old = '''        if (!recoveryStore.reserve(connection.baseUrl, authority.encode())) {\n            error = "Start blev ikke sendt, fordi recovery-authority ikke kunne gemmes sikkert lokalt."\n            return\n        }\n'''
new = '''        val reservation = recoveryStore.reserve(connection.baseUrl, authority.encode()) ?: run {\n            error = "Start blev ikke sendt, fordi recovery-authority ikke kunne gemmes sikkert lokalt."\n            return\n        }\n'''
if text.count(old) != 1:
    raise SystemExit("android UI: reserve anchor drift")
text = text.replace(old, new, 1)
text = text.replace(
    "publishReviewedStart(it, connection, authority)",
    "publishReviewedStart(it, connection, authority, reservation)",
)
text = text.replace(
    "publishReviewedStartFailure(it, connection, authority)",
    "publishReviewedStartFailure(it, connection, authority, reservation)",
)
if text.count("publishReviewedStart(it, connection, authority, reservation)") != 2:
    raise SystemExit("android UI: expected two handle-bound success callbacks")
if text.count("publishReviewedStartFailure(it, connection, authority, reservation)") != 2:
    raise SystemExit("android UI: expected two handle-bound failure callbacks")
write(android_ui, text)

# Desktop mirrors Android, including stale connection completion handling.
desktop_ui = "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/Agent3ReviewDevApp.kt"
replace_once(
    desktop_ui,
    "import dk.ternedal.modelrig.desktop.data.Agent3ReviewedStartRecoveryStore\n",
    "import dk.ternedal.modelrig.desktop.data.Agent3ReviewedStartRecoveryReservation\nimport dk.ternedal.modelrig.desktop.data.Agent3ReviewedStartRecoveryStore\n",
)
text = read(desktop_ui)
text = text.replace(
    "            authority: Agent3ReviewedStartRecoveryAuthority,\n        ) {",
    "            authority: Agent3ReviewedStartRecoveryAuthority,\n            reservation: Agent3ReviewedStartRecoveryReservation,\n        ) {",
)
if text.count("reservation: Agent3ReviewedStartRecoveryReservation") != 2:
    raise SystemExit("desktop UI: expected two reservation callback parameters")
text = text.replace(
    "recoveryStore.clearIfMatches(connection.baseUrl, authority.encode())",
    "recoveryStore.clearIfMatches(connection.baseUrl, reservation)",
)
if "clearIfMatches(connection.baseUrl, authority.encode())" in text:
    raise SystemExit("desktop UI: stale authority-only clear remains")
old = '''            val raw = recoveryStore.read(connection.baseUrl)\n            val authority = Agent3ReviewedStartRecoveryAuthority.decode(raw)\n            if (authority == null) {\n'''
new = '''            val reservation = recoveryStore.readReservation(connection.baseUrl)\n            val raw = reservation?.encodedAuthority ?: recoveryStore.read(connection.baseUrl)\n            val authority = Agent3ReviewedStartRecoveryAuthority.decode(raw)\n            if (authority == null || reservation == null) {\n'''
if text.count(old) != 1:
    raise SystemExit("desktop UI: recovery read anchor drift")
text = text.replace(old, new, 1)
old = '''            if (!recoveryStore.reserve(connection.baseUrl, authority.encode())) {\n                error = "Start blev ikke sendt, fordi recovery-authority ikke kunne gemmes sikkert lokalt."\n                return\n            }\n'''
new = '''            val reservation = recoveryStore.reserve(connection.baseUrl, authority.encode()) ?: run {\n                error = "Start blev ikke sendt, fordi recovery-authority ikke kunne gemmes sikkert lokalt."\n                return\n            }\n'''
if text.count(old) != 1:
    raise SystemExit("desktop UI: reserve anchor drift")
text = text.replace(old, new, 1)
text = text.replace(
    "publishReviewedStart(it, connection, authority)",
    "publishReviewedStart(it, connection, authority, reservation)",
)
text = text.replace(
    "publishReviewedStartFailure(it, connection, authority)",
    "publishReviewedStartFailure(it, connection, authority, reservation)",
)
if text.count("publishReviewedStart(it, connection, authority, reservation)") != 2:
    raise SystemExit("desktop UI: expected two handle-bound success callbacks")
if text.count("publishReviewedStartFailure(it, connection, authority, reservation)") != 2:
    raise SystemExit("desktop UI: expected two handle-bound failure callbacks")
write(desktop_ui, text)

android_test = r'''package dk.ternedal.modelrig.data

import android.content.Context
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment

@RunWith(RobolectricTestRunner::class)
class Agent3ReviewedStartRecoveryPersistenceTest {
    private lateinit var context: Context

    @Before
    fun resetPreferences() {
        context = RuntimeEnvironment.getApplication().applicationContext
        context.getSharedPreferences("modelrig", Context.MODE_PRIVATE).edit().clear().commit()
    }

    @Test
    fun `authority reservation is CAS and credential bound across store instances`() {
        val rigA = "https://rig-a.example:8443/"
        val rigB = "https://rig-b.example:8443"
        val first = "{\"schema\":\"authority-a-${System.nanoTime()}\"}"
        val second = "{\"schema\":\"authority-b-${System.nanoTime()}\"}"
        var token = "token-a"

        val storeA = Agent3ReviewedStartRecoveryStore(context) { token }
        val storeB = Agent3ReviewedStartRecoveryStore(context) { token }
        val firstReservation = requireNotNull(storeA.reserve(rigA, first))
        assertNull(storeB.reserve(rigA, second))
        assertEquals(first, storeB.read("https://rig-a.example:8443"))
        assertNull(storeA.read(rigB))
        val otherRigReservation = requireNotNull(storeB.reserve(rigB, second))
        assertFalse(storeB.clearIfMatches(rigA, otherRigReservation))
        assertEquals(first, storeA.read(rigA))

        token = "token-b"
        val mismatched = storeB.read(rigA)
        assertNotNull(mismatched)
        assertNotEquals(first, mismatched)
        assertNull(storeB.readReservation(rigA))

        token = "token-a"
        assertEquals(first, storeA.read(rigA))
        assertTrue(storeA.clearIfMatches(rigA, firstReservation))
        assertNull(storeB.read(rigA))
    }

    @Test
    fun `stale generation handle cannot clear newer reused authority after newer read`() {
        val rig = "https://aba-rig-${System.nanoTime()}.example"
        val authority = "{\"schema\":\"same-authority-${System.nanoTime()}\"}"
        val store = Agent3ReviewedStartRecoveryStore(context) { "token-a" }
        val prefs = context.getSharedPreferences("modelrig", Context.MODE_PRIVATE)
        val key = requireNotNull(agent3ReviewedStartRecoveryStorageKey(rig))

        val staleReservation = requireNotNull(store.reserve(rig, authority))
        val originalEnvelope = requireNotNull(prefs.getString(key, null))
        val parts = originalEnvelope.split('\n', limit = 4)
        assertEquals(4, parts.size)
        assertEquals("kaliv-agent3-reviewed-start-storage/v3", parts[0])

        val replacementGeneration = if (parts[2] == "11111111-1111-4111-8111-111111111111") {
            "22222222-2222-4222-8222-222222222222"
        } else {
            "11111111-1111-4111-8111-111111111111"
        }
        val replacementEnvelope = listOf(parts[0], parts[1], replacementGeneration, parts[3]).joinToString("\n")

        assertTrue(prefs.edit().remove(key).commit())
        assertTrue(prefs.edit().putString(key, replacementEnvelope).commit())

        val freshReservation = requireNotNull(store.readReservation(rig))
        assertEquals(authority, freshReservation.encodedAuthority)
        assertFalse(store.clearIfMatches(rig, staleReservation))
        assertEquals(replacementEnvelope, prefs.getString(key, null))
        assertTrue(store.clearIfMatches(rig, freshReservation))
        assertNull(prefs.getString(key, null))
    }

    @Test
    fun `legacy v2 credential-bound authority stays unresolved instead of being adopted`() {
        val rig = "https://legacy-v2-${System.nanoTime()}.example"
        val encoded = "{\"schema\":\"legacy-v2-authority\"}"
        val key = requireNotNull(agent3ReviewedStartRecoveryStorageKey(rig))
        val raw = "kaliv-agent3-reviewed-start-storage/v2\n${"a".repeat(64)}\n$encoded"
        val prefs = context.getSharedPreferences("modelrig", Context.MODE_PRIVATE)
        assertTrue(prefs.edit().putString(key, raw).commit())

        val store = Agent3ReviewedStartRecoveryStore(context) { "token-a" }
        val visible = store.read(rig)
        assertNotNull(visible)
        assertNotEquals(encoded, visible)
        assertNull(store.readReservation(rig))
        assertEquals(raw, prefs.getString(key, null))
    }

    @Test
    fun `legacy unbound authority stays unresolved and is never adopted by current credential`() {
        val rig = "https://legacy-rig-${System.nanoTime()}.example"
        val encoded = "{\"schema\":\"legacy-authority\"}"
        val key = requireNotNull(agent3ReviewedStartRecoveryStorageKey(rig))
        assertTrue(
            context.getSharedPreferences("modelrig", Context.MODE_PRIVATE)
                .edit()
                .putString(key, encoded)
                .commit()
        )

        val store = Agent3ReviewedStartRecoveryStore(context) { "token-a" }
        val visible = store.read(rig)
        assertNotNull(visible)
        assertNotEquals(encoded, visible)
        assertNull(store.readReservation(rig))
        val persisted = context.getSharedPreferences("modelrig", Context.MODE_PRIVATE).getString(key, null)
        assertEquals(encoded, persisted)
    }
}
'''
write("android/app/src/test/java/dk/ternedal/modelrig/data/Agent3ReviewedStartRecoveryPersistenceTest.kt", android_test)

desktop_test = r'''package dk.ternedal.modelrig.desktop.data

import java.nio.file.Files
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class Agent3ReviewedStartRecoveryPersistenceTest {
    private object TestProtector : CredentialProtector {
        override fun protect(plaintext: String): String = "test:$plaintext"
        override fun unprotect(envelope: String): String = envelope.removePrefix("test:")
        override fun isProtected(value: String): Boolean = value.startsWith("test:")
    }

    @Test
    fun authorityReservationIsCrossConnectionCasRigAndCredentialScoped() {
        val dbPath = Files.createTempFile("modelrig-reviewed-start-", ".db").toString()
        val rigA = "https://rig-a.example:8443/"
        val rigB = "https://rig-b.example:8443"
        val first = "{\"schema\":\"authority-a-${System.nanoTime()}\"}"
        val second = "{\"schema\":\"authority-b-${System.nanoTime()}\"}"
        var token = "token-a"

        DesktopChatDb(dbPath, TestProtector).use { dbA ->
            DesktopChatDb(dbPath, TestProtector).use { dbB ->
                val storeA = Agent3ReviewedStartRecoveryStore(dbA) { token }
                val storeB = Agent3ReviewedStartRecoveryStore(dbB) { token }
                val firstReservation = requireNotNull(storeA.reserve(rigA, first))
                assertNull(storeB.reserve(rigA, second))
                assertEquals(first, storeB.read("https://rig-a.example:8443"))
                assertNull(storeA.read(rigB))
                val otherRigReservation = requireNotNull(storeB.reserve(rigB, second))
                assertFalse(storeB.clearIfMatches(rigA, otherRigReservation))
                assertEquals(first, storeA.read(rigA))

                token = "token-b"
                val mismatched = storeB.read(rigA)
                assertNotNull(mismatched)
                assertNotEquals(first, mismatched)
                assertNull(storeB.readReservation(rigA))

                token = "token-a"
                assertEquals(first, storeA.read(rigA))
                assertTrue(storeA.clearIfMatches(rigA, firstReservation))
                assertNull(storeB.read(rigA))
            }
        }
    }

    @Test
    fun staleGenerationHandleCannotClearNewerReusedAuthorityAfterNewerRead() {
        val dbPath = Files.createTempFile("modelrig-reviewed-start-aba-", ".db").toString()
        val rig = "https://aba-rig-${System.nanoTime()}.example"
        val authority = "{\"schema\":\"same-authority-${System.nanoTime()}\"}"

        DesktopChatDb(dbPath, TestProtector).use { db ->
            val store = Agent3ReviewedStartRecoveryStore(db) { "token-a" }
            val key = requireNotNull(agent3ReviewedStartRecoveryStorageKey(rig))
            val staleReservation = requireNotNull(store.reserve(rig, authority))
            val originalEnvelope = requireNotNull(db.getSetting(key))
            val parts = originalEnvelope.split('\n', limit = 4)
            assertEquals(4, parts.size)
            assertEquals("kaliv-agent3-reviewed-start-storage/v3", parts[0])

            val replacementGeneration = if (parts[2] == "11111111-1111-4111-8111-111111111111") {
                "22222222-2222-4222-8222-222222222222"
            } else {
                "11111111-1111-4111-8111-111111111111"
            }
            val replacementEnvelope = listOf(parts[0], parts[1], replacementGeneration, parts[3]).joinToString("\n")

            assertTrue(db.removeRawSettingIfValue(key, originalEnvelope))
            assertTrue(db.putRawSettingIfAbsent(key, replacementEnvelope))

            val freshReservation = requireNotNull(store.readReservation(rig))
            assertEquals(authority, freshReservation.encodedAuthority)
            assertFalse(store.clearIfMatches(rig, staleReservation))
            assertEquals(replacementEnvelope, db.getSetting(key))
            assertTrue(store.clearIfMatches(rig, freshReservation))
            assertNull(db.getSetting(key))
        }
    }

    @Test
    fun legacyV2CredentialBoundAuthorityStaysUnresolvedInsteadOfBeingAdopted() {
        val dbPath = Files.createTempFile("modelrig-reviewed-start-v2-", ".db").toString()
        val rig = "https://legacy-v2-${System.nanoTime()}.example"
        val encoded = "{\"schema\":\"legacy-v2-authority\"}"

        DesktopChatDb(dbPath, TestProtector).use { db ->
            val key = requireNotNull(agent3ReviewedStartRecoveryStorageKey(rig))
            val raw = "kaliv-agent3-reviewed-start-storage/v2\n${"a".repeat(64)}\n$encoded"
            db.putSetting(key, raw)
            val store = Agent3ReviewedStartRecoveryStore(db) { "token-a" }
            val visible = store.read(rig)
            assertNotNull(visible)
            assertNotEquals(encoded, visible)
            assertNull(store.readReservation(rig))
            assertEquals(raw, db.getSetting(key))
        }
    }

    @Test
    fun legacyUnboundAuthorityStaysUnresolvedAndIsNeverAdoptedByCurrentCredential() {
        val dbPath = Files.createTempFile("modelrig-reviewed-start-legacy-", ".db").toString()
        val rig = "https://legacy-rig-${System.nanoTime()}.example"
        val encoded = "{\"schema\":\"legacy-authority\"}"

        DesktopChatDb(dbPath, TestProtector).use { db ->
            val key = requireNotNull(agent3ReviewedStartRecoveryStorageKey(rig))
            db.putSetting(key, encoded)
            val store = Agent3ReviewedStartRecoveryStore(db) { "token-a" }
            val visible = store.read(rig)
            assertNotNull(visible)
            assertNotEquals(encoded, visible)
            assertNull(store.readReservation(rig))
            assertEquals(encoded, db.getSetting(key))
        }
    }
}
'''
write("desktop/composeApp/src/test/kotlin/dk/ternedal/modelrig/desktop/data/Agent3ReviewedStartRecoveryPersistenceTest.kt", desktop_test)

print("applied P1m/P1n backup and generation-handle fixes")
