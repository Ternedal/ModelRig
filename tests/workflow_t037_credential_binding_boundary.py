from __future__ import annotations

import ast
import hashlib
import hmac
import json
import os
import sys
import tempfile
from pathlib import Path

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(root_dir, "worker"))

from app.read_connector_credential_vault import (  # noqa: E402
    CredentialVaultScope,
    ReadConnectorCredentialVault,
    ReadConnectorCredentialVaultError,
    WindowsDpapiCredentialProtector,
)

passed = failed = 0


def check(cond: bool, label: str) -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


def raises(exc_type, fn, contains: str) -> bool:
    try:
        fn()
    except exc_type as exc:
        return contains in str(exc)
    return False


def imports_for(source: str) -> tuple[set[str], set[str]]:
    tree = ast.parse(source)
    imported: set[str] = set()
    imported_full: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".", 1)[0])
                imported_full.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", 1)[0])
            imported_full.add(node.module)
    return imported, imported_full


class FakeProtector:
    provider_id = "test-aead-current-user"
    key_scope = "current-user"

    def __init__(self) -> None:
        self.key = b"t037-vault-test-key-not-production"
        self.counter = 0
        self.protect_calls = 0
        self.unprotect_calls = 0

    def _stream(self, entropy: bytes, nonce: bytes, length: int) -> bytes:
        result = bytearray()
        block = 0
        while len(result) < length:
            result.extend(
                hmac.new(
                    self.key,
                    b"stream\0" + entropy + nonce + block.to_bytes(4, "big"),
                    hashlib.sha256,
                ).digest()
            )
            block += 1
        return bytes(result[:length])

    def protect(self, plaintext: bytes, *, entropy: bytes) -> bytes:
        self.protect_calls += 1
        self.counter += 1
        nonce = hashlib.sha256(
            self.key + entropy + self.counter.to_bytes(8, "big")
        ).digest()[:16]
        stream = self._stream(entropy, nonce, len(plaintext))
        encrypted = bytes(left ^ right for left, right in zip(plaintext, stream))
        tag = hmac.new(
            self.key, b"tag\0" + entropy + nonce + encrypted, hashlib.sha256
        ).digest()
        return nonce + tag + encrypted

    def unprotect(self, ciphertext: bytes, *, entropy: bytes) -> bytes:
        self.unprotect_calls += 1
        if len(ciphertext) < 48:
            raise ReadConnectorCredentialVaultError("test ciphertext invalid")
        nonce, tag, encrypted = ciphertext[:16], ciphertext[16:48], ciphertext[48:]
        expected = hmac.new(
            self.key, b"tag\0" + entropy + nonce + encrypted, hashlib.sha256
        ).digest()
        if not hmac.compare_digest(tag, expected):
            raise ReadConnectorCredentialVaultError("test ciphertext invalid")
        stream = self._stream(entropy, nonce, len(encrypted))
        return bytes(left ^ right for left, right in zip(encrypted, stream))


def static_binding_checks() -> None:
    path = os.path.join(
        root_dir, "worker", "app", "read_connector_credential_binding.py"
    )
    source = open(path, encoding="utf-8").read()
    imported, imported_full = imports_for(source)

    check(
        {
            "socket",
            "ssl",
            "http",
            "urllib",
            "requests",
            "httpx",
            "aiohttp",
            "subprocess",
            "pathlib",
        }.isdisjoint(imported),
        "credential binding imports no network/process/file credential implementation",
    )
    check("os" not in imported, "credential binding cannot read environment configuration")
    check(
        "pinned_http_transport" not in imported_full,
        "credential slice cannot accidentally become live transport",
    )

    for needle in (
        "os.getenv(",
        "os.environ",
        "Path(",
        "open(",
        "read_bytes(",
        "socket.",
        "requests.",
        "httpx.",
        "aiohttp.",
        "urlopen(",
        "subprocess.",
        "request_with_trusted_bearer(",
        "FastAPI(",
        "APIRouter(",
        "REGISTRY[",
        "chat_tools(",
        "Authorization: Bearer",
    ):
        check(needle not in source, f"credential binding remains dormant: no {needle}")

    tree = ast.parse(source)
    call_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                call_names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                call_names.add(node.func.attr)
    check(
        {"socket", "urlopen", "register", "include_router"}.isdisjoint(call_names),
        "credential module has no concrete network/registration call site",
    )
    check(
        "PRODUCTION_ACTIVATION = False" in source,
        "credential binding pins production activation false",
    )
    check(
        'credential_mode != "bearer_injected_at_execute"' in source,
        "credential boundary requires execute-time bearer mode from provider plan",
    )
    check(
        "follow_redirects is not False" in source,
        "credential boundary rechecks redirect denial",
    )
    check(
        source.count("self._grants.authorize(") >= 2,
        "grant authority is checked both at prepare and execution boundaries",
    )
    check(
        "self._credentials.bearer_token()" in source,
        "bearer material has one explicit host-owned execution seam",
    )
    execution_start = source.index("def trusted_bearer_for_execution")
    check(
        source.index("self._grants.authorize(", execution_start)
        < source.index("self._credentials.bearer_token()", execution_start),
        "execution re-authorizes grant before reading bearer material",
    )
    check(
        '"www.googleapis.com"' in source
        and '"gmail.googleapis.com"' in source
        and '"api.notion.com"' in source,
        "credential boundary pins connector-specific provider hosts",
    )
    check(
        '"google_oauth_bearer"' in source
        and '"notion_integration_bearer"' in source,
        "credential kinds are provider-specific and closed",
    )
    check(
        "to_audit_dict" in source
        and '"credential_kind"' in source
        and '"scope_sha256"' in source,
        "non-secret audit binds credential kind and exact scope authority",
    )
    audit_start = source.index("def to_audit_dict")
    audit_end = source.index("class ReadConnectorCredentialBinder")
    check(
        '"token"' not in source[audit_start:audit_end],
        "audit projection contains no token field",
    )


def static_vault_checks() -> None:
    path = os.path.join(
        root_dir, "worker", "app", "read_connector_credential_vault.py"
    )
    source = open(path, encoding="utf-8").read()
    imported, _ = imports_for(source)
    check(
        {
            "socket",
            "ssl",
            "http",
            "urllib",
            "requests",
            "httpx",
            "aiohttp",
            "subprocess",
        }.isdisjoint(imported),
        "credential vault imports no provider network/process client",
    )
    for needle in (
        "os.getenv(",
        "os.environ",
        "FastAPI(",
        "APIRouter(",
        "REGISTRY[",
        "chat_tools(",
        "Authorization: Bearer",
        "request_with_trusted_bearer(",
        "request_with_trusted_bearer_request(",
    ):
        check(needle not in source, f"credential vault remains unregistered/offline: no {needle}")
    check(
        "PRODUCTION_ACTIVATION = False" in source,
        "credential vault pins production activation false",
    )
    check(
        "root_path.is_absolute()" in source,
        "credential vault requires explicit absolute storage root",
    )
    check(
        "CryptProtectData" in source
        and "CryptUnprotectData" in source
        and "_CRYPTPROTECT_UI_FORBIDDEN" in source,
        "credential vault has concrete Windows current-user DPAPI protection",
    )
    check(
        "os.replace(" in source and "os.fsync(" in source,
        "credential vault commits records atomically and durably",
    )
    check(
        "os.chmod(self._root, 0o700)" in source
        and "os.chmod(destination, 0o600)" in source,
        "POSIX fallback narrows vault directory and record permissions",
    )
    check(
        'purpose not in {"evidence", "bearer"}' in source
        and "evidence_ciphertext_sha256=evidence_ciphertext_sha256" in source,
        "bearer ciphertext is domain-separated and bound to evidence ciphertext",
    )


def behavioral_vault_checks() -> None:
    token = "drive-vault-secret-token-1234567890abcd"
    account = "google-account-vault-1"
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp).resolve() / "credentials"
        protector = FakeProtector()
        scope = CredentialVaultScope(
            connector="google_drive",
            account_ref=account,
        )
        vault = ReadConnectorCredentialVault(
            root=root,
            scope=scope,
            protector=protector,
        )

        missing = vault.evidence(now=100)
        check(missing.state == "missing_credentials", "missing vault record is explicit")
        check(not root.exists(), "readiness check does not create missing vault root")
        check(protector.unprotect_calls == 0, "missing readiness decrypts nothing")
        check(
            raises(
                ReadConnectorCredentialVaultError,
                lambda: vault.store_bearer(token, now=100),
                "requires expires_at",
            ),
            "Google OAuth bearer cannot be persisted without expiry",
        )

        vault.store_bearer(token, now=100, expires_at=500)
        files = list(root.glob("*.credential.json"))
        check(len(files) == 1, "one exact credential scope persists one hashed record")
        raw = files[0].read_text(encoding="utf-8")
        check(token not in raw, "persisted vault envelope contains no bearer plaintext")
        check(account not in raw, "persisted vault envelope contains no account plaintext")
        check("google_drive" not in raw, "persisted vault envelope contains no connector identity plaintext")

        before = protector.unprotect_calls
        ready = vault.evidence(now=101)
        check(ready.state == "ready", "valid encrypted Google credential reports ready")
        check(ready.account_ref == account, "ready evidence restores exact account identity")
        check(ready.expires_at == 500, "ready evidence restores exact expiry")
        check(
            protector.unprotect_calls == before + 1,
            "readiness decrypts evidence only, not bearer material",
        )

        before = protector.unprotect_calls
        check(vault.bearer_token() == token, "trusted provider seam decrypts exact bearer")
        check(
            protector.unprotect_calls == before + 2,
            "bearer seam first validates encrypted evidence then decrypts bearer",
        )
        expired = vault.evidence(now=500)
        check(expired.state == "expired_credentials", "expiry is classified exactly at boundary")

        envelope = json.loads(files[0].read_text(encoding="utf-8"))
        encoded = envelope["evidence_ciphertext_b64"]
        replacement = ("A" if encoded[0] != "A" else "B") + encoded[1:]
        envelope["evidence_ciphertext_b64"] = replacement
        files[0].write_text(
            json.dumps(envelope, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        invalid = vault.evidence(now=200)
        check(invalid.state == "invalid_credentials", "ciphertext tamper fails closed as invalid")
        check(
            raises(
                ReadConnectorCredentialVaultError,
                vault.bearer_token,
                "ciphertext digest mismatch",
            ),
            "tampered record never releases bearer material",
        )

        vault.store_bearer(token, now=300, expires_at=900)
        check(vault.revoke(now=301), "host can durably revoke stored credential")
        revoked = vault.evidence(now=302)
        check(revoked.state == "invalid_credentials", "revoked credential is no longer ready")
        before = protector.unprotect_calls
        check(
            raises(
                ReadConnectorCredentialVaultError,
                vault.bearer_token,
                "unavailable",
            ),
            "revoked credential cannot release bearer",
        )
        check(
            protector.unprotect_calls == before + 1,
            "revoked credential stops after evidence decryption",
        )
        check(not vault.revoke(now=303), "credential revoke is idempotent")
        check(vault.clear(), "host can clear encrypted credential record")
        check(vault.evidence(now=304).state == "missing_credentials", "cleared credential becomes missing")
        check(not vault.clear(), "credential clear is idempotent")

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp).resolve() / "notion-credentials"
        protector = FakeProtector()
        notion_token = "notion-secret-token-1234567890abcdef"
        notion_scope = CredentialVaultScope(
            connector="notion",
            account_ref="notion-account-1",
            workspace_ref="workspace-main",
        )
        notion = ReadConnectorCredentialVault(
            root=root,
            scope=notion_scope,
            protector=protector,
        )
        notion.store_bearer(notion_token, now=400)
        check(notion.evidence(now=401).state == "ready", "Notion integration bearer may be non-expiring")
        check(notion.bearer_token() == notion_token, "Notion bearer roundtrips through encrypted vault")
        raw = next(root.glob("*.credential.json")).read_text(encoding="utf-8")
        check("workspace-main" not in raw, "Notion workspace identity stays encrypted at rest")
        wrong_workspace = ReadConnectorCredentialVault(
            root=root,
            scope=CredentialVaultScope(
                connector="notion",
                account_ref="notion-account-1",
                workspace_ref="workspace-other",
            ),
            protector=protector,
        )
        check(
            wrong_workspace.evidence(now=402).state == "missing_credentials",
            "different workspace resolves to a different credential record",
        )

    check(
        raises(
            ReadConnectorCredentialVaultError,
            lambda: ReadConnectorCredentialVault(
                root="relative-vault",
                scope=CredentialVaultScope(
                    connector="gmail",
                    account_ref="google-account-2",
                ),
                protector=FakeProtector(),
            ),
            "absolute path",
        ),
        "vault cannot fall back to working-directory-relative storage",
    )
    check(
        raises(
            ReadConnectorCredentialVaultError,
            lambda: WindowsDpapiCredentialProtector(os_name="posix"),
            "requires Windows DPAPI",
        ),
        "concrete DPAPI protector fails closed off Windows",
    )


def main() -> int:
    static_binding_checks()
    static_vault_checks()
    behavioral_vault_checks()
    print(f"\n===== T-037 CREDENTIAL BOUNDARY: {passed} passed, {failed} failed =====")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
