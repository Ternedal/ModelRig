from pathlib import Path

module = Path("worker/app/research_peer_binding.py")
text = module.read_text(encoding="utf-8")
old = '''_ERROR_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
'''
new = '''_ERROR_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RECEIPT_ID_RE = re.compile(r"^egr_[a-z0-9._-]{1,96}$")
_CONSENT_ID_RE = re.compile(r"^egc_[a-z0-9._-]{1,96}$")
'''
if text.count(old) != 1:
    raise SystemExit("expected digest regex block exactly once")
text = text.replace(old, new)

old = '''    if not isinstance(receipt, EgressReceipt):
        raise PeerBindingContractError("receipt must be an EgressReceipt")
    if receipt.plan_digest != plan.digest:
'''
new = '''    if not isinstance(receipt, EgressReceipt):
        raise PeerBindingContractError("receipt must be an EgressReceipt")
    if not isinstance(receipt.receipt_id, str) or not _RECEIPT_ID_RE.fullmatch(receipt.receipt_id):
        raise PeerBindingContractError("egress receipt_id has an invalid format")
    for name, value in (("authorized_at", receipt.authorized_at), ("expires_at", receipt.expires_at)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise PeerBindingContractError(f"egress {name} must be a non-negative integer timestamp")
    if receipt.expires_at <= receipt.authorized_at:
        raise PeerBindingContractError("egress receipt expiry must follow authorization")
    if receipt.authorization not in {"automatic", "consented"}:
        raise PeerBindingContractError("egress receipt authorization is invalid")
    if receipt.authorization == "automatic" and receipt.consent_id is not None:
        raise PeerBindingContractError("automatic egress receipt cannot include consent_id")
    if receipt.authorization == "consented":
        if not isinstance(receipt.consent_id, str) or not _CONSENT_ID_RE.fullmatch(receipt.consent_id):
            raise PeerBindingContractError("consented egress receipt requires a valid consent_id")
    if receipt.plan_digest != plan.digest:
'''
if text.count(old) != 1:
    raise SystemExit("expected egress validation block exactly once")
module.write_text(text.replace(old, new), encoding="utf-8")

test = Path("tests/worker_research_peer_binding.py")
content = test.read_text(encoding="utf-8")
marker = '''wrong_limit = replace(RECEIPT, max_bytes=4097)
rejects(
    lambda: scope_ledger.issue(PLAN, wrong_limit, RAW_URL, now=110),
    PeerBindingDenied,
    "receipt byte ceiling must match plan",
)
'''
addition = marker + '''for invalid_receipt, name in (
    (replace(RECEIPT, receipt_id=""), "empty receipt id is rejected"),
    (replace(RECEIPT, authorized_at=True), "boolean authorization timestamp is rejected"),
    (replace(RECEIPT, expires_at=100), "receipt expiry must follow authorization"),
    (replace(RECEIPT, authorization="unknown"), "unknown receipt authorization is rejected"),
    (replace(RECEIPT, authorization="automatic", consent_id="egc_test_consent"), "automatic receipt cannot carry consent"),
    (replace(RECEIPT, authorization="consented", consent_id=None), "consented receipt requires consent id"),
):
    before = list(scope_ledger.events())
    rejects(
        lambda value=invalid_receipt: scope_ledger.issue(PLAN, value, RAW_URL, now=110),
        PeerBindingContractError,
        name,
    )
    check(scope_ledger.events() == before, f"{name} leaves no audit row")
'''
if content.count(marker) != 1:
    raise SystemExit("expected receipt-limit test block exactly once")
test.write_text(content.replace(marker, addition), encoding="utf-8")
