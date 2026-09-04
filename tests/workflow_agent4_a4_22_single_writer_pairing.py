#!/usr/bin/env python3
"""Repository contract for A4-22 pairing/device-store single-writer ownership."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "backend" / "cmd" / "modelrig-server" / "main.go"
TEST = ROOT / "backend" / "cmd" / "modelrig-server" / "main_test.go"
GRANT_CLI = ROOT / "backend" / "cmd" / "modelrig-agent4-grants" / "main.go"


def function_body(source: str, name: str, next_name: str) -> str:
    start = source.index(f"func {name}")
    end = source.index(f"func {next_name}", start)
    return source[start:end]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAIL: {message}")


def main() -> None:
    source = MAIN.read_text(encoding="utf-8")
    tests = TEST.read_text(encoding="utf-8")
    grant_cli = GRANT_CLI.read_text(encoding="utf-8")
    pair_cli = function_body(source, "pairCLI", "pairServerBaseURL")

    for forbidden in (
        "store.Open",
        "PutPairing",
        "pairing.Code",
        "cfg.DataPath",
    ):
        require(
            forbidden not in pair_cli,
            f"pairCLI regained direct device-store mutation via {forbidden}",
        )

    require(
        "requestPairStart(baseURL)" in pair_cli,
        "pairCLI must delegate pairing mutation to the running backend",
    )
    require(
        'case "0.0.0.0":' in source and 'host = "127.0.0.1"' in source,
        "wildcard IPv4 bind must be discoverable through local loopback",
    )
    require(
        'case "::":' in source and 'host = "::1"' in source,
        "wildcard IPv6 bind must be discoverable through local loopback",
    )
    require(
        "net.JoinHostPort(host, strconv.Itoa(cfg.ServerPort))" in source,
        "concrete LAN/Tailscale and IPv6 binds must use the configured owner address",
    )
    require(
        "http.ErrUseLastResponse" in source,
        "pairing client must not follow redirects to another authority",
    )

    # A4-16 grant administration is the other supported security-state CLI.
    # Keep it on the live backend too: no future refactor may make it a second
    # JSON writer while pairing has been hardened.
    for forbidden in (
        '"modelrig/internal/store"',
        "store.Open",
        "SetAgent4ReadGrant",
        "os.WriteFile",
    ):
        require(
            forbidden not in grant_cli,
            f"agent4 grant CLI regained direct device-store mutation via {forbidden}",
        )
    require(
        "client.Do(request)" in grant_cli,
        "agent4 grant CLI must continue delegating mutation to the backend API",
    )
    require(
        'request.Header.Set("X-Admin-Key", adminKey)' in grant_cli,
        "agent4 grant CLI must retain authenticated backend mutation",
    )

    for required_test in (
        "TestPairCLIOfflineFailsClosedWithoutTouchingStore",
        "TestPairCLIReachableFailureNeverFallsBackToStore",
        "TestPairCLISuccessUsesServerAndNeverTouchesConfiguredStore",
        "TestRequestPairStartDoesNotFollowRedirect",
        "TestPairAndGrantRevokeShareOneLiveStoreWriter",
    ):
        require(required_test in tests, f"missing adversarial A4-22 test {required_test}")

    print("PASS: A4-22 pairing/grant CLIs remain API-only and the backend remains sole store writer")


if __name__ == "__main__":
    main()
