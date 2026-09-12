from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"expected exactly one patch anchor in {path}, found {text.count(old)}")
    target.write_text(text.replace(old, new), encoding="utf-8")


replace_once(
    "worker/app/agent3/planner.py",
    '''            if reviewing:\n                kwargs["review_reads"] = review_reads\n            run = orchestrator.start_with_steps(\n''',
    '''            if reviewing:\n                kwargs["review_reads"] = review_reads\n                # A reviewed run must never become externally observable without\n                # its read-review policy. ReviewingAgent3Orchestrator already\n                # configures normal routed runs before saving them, but its\n                # blocked-route path uses the base blocked-run helper. Persist the\n                # policy here before either path can materialize the reserved run.\n                orchestrator.review_store.configure(reserved_run_id, review_reads)\n            run = orchestrator.start_with_steps(\n''',
)

planner_test = Path("tests/worker_agent3_planner_review.py")
planner_text = planner_test.read_text(encoding="utf-8")
anchor = '''assert executed[-2:] == ["rig_status", "list_models"]\n\nprint("19 passed, 0 failed")\n'''
replacement = '''assert executed[-2:] == ["rig_status", "list_models"]\n\n# Route/capability drift between Preview and Start may materialize a BLOCKED\n# run. Even that run is externally observable and must carry the exact reviewed\n# policy before it is persisted; otherwise a missing row defaults to\n# enabled=False and same-plan recovery wedges on a raw review_reads mismatch.\ndrift_preview = client.post(\n    "/experimental/agent3/plan",\n    json={"message": "check rig before route drift", "mode": "rig", "review_reads": True},\n)\nassert drift_preview.status_code == 200, drift_preview.text\ndrift_body = drift_preview.json()\nGate.enabled = False\ntry:\n    drift_started = client.post(\n        f"/experimental/agent3/plans/{drift_body['plan_id']}/start"\n    )\nfinally:\n    Gate.enabled = True\nassert drift_started.status_code == 200, drift_started.text\ndrift_run = drift_started.json()\nassert drift_run["run"]["state"] == "blocked"\nassert drift_run["review_reads"] is True\nassert drift_run["read_review"]["enabled"] is True\nassert drift_run["read_review"]["waiting"] is False\n\ndrift_replay = client.post(\n    f"/experimental/agent3/plans/{drift_body['plan_id']}/start"\n)\nassert drift_replay.status_code == 200, drift_replay.text\nassert drift_replay.json()["run"]["id"] == drift_run["run"]["id"]\nassert drift_replay.json()["read_review"]["enabled"] is True\n\nprint("27 passed, 0 failed")\n'''
if planner_text.count(anchor) != 1:
    raise SystemExit("planner review test anchor changed")
planner_test.write_text(planner_text.replace(anchor, replacement), encoding="utf-8")

replace_once(
    "backend/internal/proxy/proxy.go",
    '''\t// Integrity attestations for renderer clients (body id, package and\n\t// member digests) ride on X-BodyRig-* and are meaningless without a way\n\t// to reach the client. A prefix, not a blanket copy: upstream internals\n\t// still stop here.\n\tfor name, values := range resp.Header {\n\t\tif !strings.HasPrefix(http.CanonicalHeaderKey(name), "X-Bodyrig-") {\n\t\t\tcontinue\n\t\t}\n\t\tfor _, v := range values {\n\t\t\tw.Header().Add(name, v)\n\t\t}\n\t}\n''',
    '''\t// Integrity attestations for renderer clients (body id, package and\n\t// member digests) ride on X-BodyRig-*. Reviewed Agent 3 Start additionally\n\t// exposes one bounded reason code so clients can distinguish a definitive\n\t// refusal from an ambiguous/lost response without trusting arbitrary worker\n\t// headers. Keep this an explicit allow-list, not a blanket copy.\n\tfor name, values := range resp.Header {\n\t\tcanonical := http.CanonicalHeaderKey(name)\n\t\tif canonical != "X-Modelrig-Agent3-Reason" &&\n\t\t\t!strings.HasPrefix(canonical, "X-Bodyrig-") {\n\t\t\tcontinue\n\t\t}\n\t\tfor _, v := range values {\n\t\t\tw.Header().Add(name, v)\n\t\t}\n\t}\n''',
)

proxy_test = Path("backend/internal/proxy/proxy_test.go")
proxy_text = proxy_test.read_text(encoding="utf-8")
proxy_anchor = '''func TestForward_PassthroughWhenUpstreamCutsEarly(t *testing.T) {\n'''
proxy_test_case = '''func TestForward_ReviewedStartReasonHeaderIsNarrowlyForwarded(t *testing.T) {\n\tup := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {\n\t\tw.Header().Set("Content-Type", "application/json")\n\t\tw.Header().Set("X-ModelRig-Agent3-Reason", "reviewed_start_refused")\n\t\tw.Header().Set("X-ModelRig-Internal", "must-not-leak")\n\t\tw.WriteHeader(http.StatusConflict)\n\t\t_, _ = fmt.Fprint(w, `{"detail":"refused"}`)\n\t}))\n\tdefer up.Close()\n\n\tc := New(up.URL, 5*time.Second)\n\treq := httptest.NewRequest("POST", "/api/v1/experimental/agent3/plans/p/start", strings.NewReader(`{}`))\n\trec := httptest.NewRecorder()\n\tc.Forward(rec, req, "/experimental/agent3/plans/p/start")\n\n\tif got := rec.Header().Get("X-ModelRig-Agent3-Reason"); got != "reviewed_start_refused" {\n\t\tt.Fatalf("reviewed Start reason = %q", got)\n\t}\n\tif got := rec.Header().Get("X-ModelRig-Internal"); got != "" {\n\t\tt.Fatalf("untrusted upstream header leaked: %q", got)\n\t}\n}\n\n'''
if proxy_text.count(proxy_anchor) != 1:
    raise SystemExit("proxy test anchor changed")
proxy_test.write_text(proxy_text.replace(proxy_anchor, proxy_test_case + proxy_anchor), encoding="utf-8")
