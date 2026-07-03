#!/usr/bin/env python3
"""ModelRig reference CLI.

A dependency-free client for the ModelRig backend: pair a device, stream chat,
list/pick models, run RAG, and manage devices. Stdlib only — runs anywhere
Python 3.9+ does (Windows included).

Config (server URL + token) is saved to ~/.modelrig/cli.json after pairing.

Examples:
    python modelrig-cli.py --url http://192.168.1.10:8080 pair --code ABCD-EFGH
    python modelrig-cli.py chat "explain the pairing flow"
    python modelrig-cli.py models
    python modelrig-cli.py rag-ingest --source notes "ModelRig binds 0.0.0.0 for LAN"
    python modelrig-cli.py rag-query "what host does it bind?"
    python modelrig-cli.py devices
    python modelrig-cli.py revoke <device_id>
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

CONFIG_DIR = os.path.expanduser("~/.modelrig")
CONFIG_PATH = os.path.join(CONFIG_DIR, "cli.json")


def die(msg, code=1):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


def resolve(args):
    cfg = load_config()
    return (args.url or cfg.get("url")), (args.token or cfg.get("token")), cfg


def call(args, method, path, body=None, need_token=True, timeout=120):
    """JSON request → returns response text. Exits cleanly on any HTTP/URL error."""
    url, token, _ = resolve(args)
    if not url:
        die("no server URL — run 'pair' first or pass --url")
    if need_token and not token:
        die("no token — run 'pair' first or pass --token")
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url.rstrip("/") + path, data=data, method=method)
    if body is not None:
        r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.read().decode()
    except urllib.error.HTTPError as e:
        die(f"{method} {path} failed ({e.code}): {e.read().decode()[:300]}")
    except urllib.error.URLError as e:
        die(f"cannot reach {url}: {e.reason}")


def cmd_pair(args):
    url, _, cfg = resolve(args)
    if not url:
        die("--url is required for pairing")
    args.url = url
    raw = call(args, "POST", "/api/v1/pair/claim",
               body={"device_name": args.name or "modelrig-cli", "code": args.code},
               need_token=False, timeout=15)
    out = json.loads(raw)
    cfg["url"] = url
    cfg["token"] = out["token"]
    cfg["device_id"] = out["device_id"]
    save_config(cfg)
    print(f"paired as {out['device_id']} ({out['device_name']}); token saved to {CONFIG_PATH}")


def cmd_status(args):
    print(call(args, "GET", "/api/v1/status"))


def cmd_models(args):
    data = json.loads(call(args, "GET", "/api/v1/models"))
    names = [m.get("name", "") for m in data.get("models", [])]
    if not any(names):
        print("(no models)")
    for n in names:
        if n:
            print(n)


def cmd_devices(args):
    data = json.loads(call(args, "GET", "/api/v1/devices"))
    devs = data.get("devices", [])
    if not devs:
        print("(no devices)")
    for d in devs:
        print(f"{d['id']}  {d['name']}  last_seen={d.get('last_seen', '')}")


def cmd_revoke(args):
    print(call(args, "DELETE", f"/api/v1/devices/{args.device_id}"))


def cmd_rotate(args):
    """Re-issue this device's token without re-pairing (e.g. after a leak)."""
    out = json.loads(call(args, "POST", "/api/v1/token/rotate"))
    cfg = load_config()
    cfg["token"] = out["token"]
    save_config(cfg)
    print(f"token rotated for device {out['device_id']} ({out['device_name']}); "
          f"new token saved. The old token is now invalid.")


def cmd_rag_ingest(args):
    body = {
        "documents": [{"text": args.text, "source": args.source}],
        "chunk_size": args.chunk_size,
        "overlap": args.overlap,
    }
    print(call(args, "POST", "/api/v1/rag/ingest", body=body))


def cmd_rag_query(args):
    body = {"query": args.query, "top_k": args.top_k, "synthesize": not args.no_synth}
    if args.model:
        body["model"] = args.model
    if args.source:
        body["source"] = args.source
    print(call(args, "POST", "/api/v1/rag/query", body=body))


def cmd_rag_chat(args):
    """Streaming RAG answer: retrieve context, then stream the answer. The context
    sources are printed to stderr; the answer streams to stdout (clean for piping)."""
    url, token, _ = resolve(args)
    if not url:
        die("no server URL — run 'pair' first or pass --url")
    if not token:
        die("no token — run 'pair' first or pass --token")
    body = {"query": args.query, "top_k": args.top_k}
    if args.model:
        body["model"] = args.model
    if args.source:
        body["source"] = args.source
    r = urllib.request.Request(url.rstrip("/") + "/api/v1/rag/chat",
                               data=json.dumps(body).encode(), method="POST")
    r.add_header("Content-Type", "application/json")
    r.add_header("Authorization", "Bearer " + token)
    try:
        resp = urllib.request.urlopen(r, timeout=300)
    except urllib.error.HTTPError as e:
        die(f"rag-chat failed ({e.code}): {e.read().decode()[:300]}")
    except urllib.error.URLError as e:
        die(f"cannot reach {url}: {e.reason}")
    head_seen = False
    for raw in resp:
        line = raw.decode(errors="replace").strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if not head_seen and "sources" in obj:
            names = ", ".join(str(s.get("source")) for s in obj["sources"]) or "(none)"
            sys.stderr.write(f"[context: {names}]\n")
            sys.stderr.flush()
            head_seen = True
            continue
        if "error" in obj:
            sys.stderr.write(f"\n[error: {obj['error']}]\n")
            break
        delta = obj.get("message", {}).get("content", "")
        if delta:
            sys.stdout.write(delta)
            sys.stdout.flush()
    sys.stdout.write("\n")


def cmd_rag_sources(args):
    data = json.loads(call(args, "GET", "/api/v1/rag/sources"))
    srcs = data.get("sources", [])
    if not srcs:
        print("(no sources)")
    for s in srcs:
        print(f"{s['source']}  chunks={s['chunks']}")


def cmd_rag_stats(args):
    print(call(args, "GET", "/api/v1/rag/stats"))


def cmd_rag_delete(args):
    import urllib.parse
    q = urllib.parse.quote(args.source, safe="")
    print(call(args, "DELETE", f"/api/v1/rag/source?source={q}"))


def cmd_chat(args):
    url, token, _ = resolve(args)
    if not url:
        die("no server URL — run 'pair' first or pass --url")
    if not token:
        die("no token — run 'pair' first or pass --token")
    body = {
        "model": args.model or "qwen2.5-coder:7b",
        "messages": [{"role": "user", "content": args.message}],
        "stream": True,
    }
    r = urllib.request.Request(url.rstrip("/") + "/api/v1/chat",
                               data=json.dumps(body).encode(), method="POST")
    r.add_header("Content-Type", "application/json")
    r.add_header("Authorization", "Bearer " + token)
    try:
        resp = urllib.request.urlopen(r, timeout=300)
    except urllib.error.HTTPError as e:
        die(f"chat failed ({e.code}): {e.read().decode()[:300]}")
    except urllib.error.URLError as e:
        die(f"cannot reach {url}: {e.reason}")
    # stream NDJSON lines as they arrive
    for raw in resp:
        line = raw.decode(errors="replace").strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        delta = obj.get("message", {}).get("content", "")
        if delta:
            sys.stdout.write(delta)
            sys.stdout.flush()
    sys.stdout.write("\n")


def cmd_whoami(args):
    cfg = load_config()
    if not cfg:
        print("(no saved config)")
        return
    tok = cfg.get("token", "")
    masked = (tok[:8] + "…") if tok else "(none)"
    print(f"url={cfg.get('url')}  device_id={cfg.get('device_id')}  token={masked}")


def _probe(url, path, token=None, timeout=5):
    """Best-effort GET returning (status_or_None, body_or_reason). Never raises."""
    r = urllib.request.Request(url.rstrip("/") + path)
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except urllib.error.URLError as e:
        return None, str(e.reason)


def cmd_doctor(args):
    url, token, _ = resolve(args)
    if not url:
        die("no server URL — run 'pair' first or pass --url")
    print(f"ModelRig doctor — target {url}")

    st, body = _probe(url, "/healthz")
    if st != 200:
        print(f"  [FAIL] backend unreachable: {body}")
        print("\ndiagnosis: backend is not responding. Is modelrig-server running and is the URL correct?")
        sys.exit(1)
    try:
        ver = json.loads(body).get("version", "?")
    except Exception:
        ver = "?"
    print(f"  [ OK ] backend reachable (version {ver})")

    if not token:
        print("  [WARN] no token saved — run 'pair' to check auth + upstreams")
        return

    st, body = _probe(url, "/api/v1/status", token=token)
    if st == 401:
        print("  [FAIL] token rejected (401) — device may be revoked; re-pair")
        sys.exit(1)
    if st != 200:
        print(f"  [FAIL] status endpoint returned {st}: {body}")
        sys.exit(1)

    d = json.loads(body)
    up, dev = d.get("upstream", {}), d.get("device", {})
    print(f"  [ OK ] token valid (device {dev.get('name')} / {dev.get('id')})")
    print(f"  [{' OK ' if up.get('ollama') else 'FAIL'}] ollama {'reachable' if up.get('ollama') else 'DOWN'} (chat / models / embeddings)")
    print(f"  [{' OK ' if up.get('worker') else 'FAIL'}] worker {'reachable' if up.get('worker') else 'DOWN'} (RAG)")

    problems = []
    if not up.get("ollama"):
        problems.append("Ollama is down — start it (ollama serve) and check MODELRIG_OLLAMA_URL")
    if not up.get("worker"):
        problems.append("RAG worker is down — start uvicorn and check MODELRIG_WORKER_URL")

    if args.deep:
        st, body = _probe(url, "/api/v1/health/deep", token=token, timeout=20)
        if st == 200:
            d = json.loads(body)
            o = d.get("checks", {}).get("ollama", {})
            wk = d.get("checks", {}).get("worker", {})
            print(f"  [{' OK ' if o.get('ok') else 'FAIL'}] ollama round-trip: models={o.get('models', '?')} ({o.get('latency_ms', '?')}ms)")
            print(f"  [{' OK ' if wk.get('ok') else 'FAIL'}] worker round-trip: embed_dims={wk.get('embed_dims', '?')} ({wk.get('latency_ms', '?')}ms)")
            if not wk.get("ok") and wk.get("error"):
                print(f"         worker error: {wk['error']}")
            if not d.get("ok"):
                problems.append("deep check failed — a model did not respond (embeddings)")
        else:
            print(f"  [FAIL] deep health returned {st}: {body}")
            problems.append("deep health endpoint failed")

    if problems:
        print("\ndiagnosis:")
        for p in problems:
            print("  - " + p)
        sys.exit(1)
    print("\ndiagnosis: all systems go.")


def build_parser():
    p = argparse.ArgumentParser(prog="modelrig", description="ModelRig reference CLI")
    p.add_argument("--url", help="server base URL (overrides saved config)")
    p.add_argument("--token", help="device token (overrides saved config)")
    p.add_argument("--config", help="path to config file (default ~/.modelrig/cli.json)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("pair", help="claim a pairing code and save the token")
    sp.add_argument("--code", required=True)
    sp.add_argument("--name")
    sp.set_defaults(fn=cmd_pair)

    sub.add_parser("status", help="device + upstream health").set_defaults(fn=cmd_status)
    dp = sub.add_parser("doctor", help="diagnose backend / worker / ollama reachability")
    dp.add_argument("--deep", action="store_true", help="also round-trip an embedding through the worker + Ollama")
    dp.set_defaults(fn=cmd_doctor)
    sub.add_parser("rotate", help="re-issue this device's token (invalidates the old one)").set_defaults(fn=cmd_rotate)
    sub.add_parser("models", help="list available models").set_defaults(fn=cmd_models)
    sub.add_parser("devices", help="list paired devices").set_defaults(fn=cmd_devices)
    sub.add_parser("whoami", help="show saved config").set_defaults(fn=cmd_whoami)

    rp = sub.add_parser("revoke", help="revoke a device by id")
    rp.add_argument("device_id")
    rp.set_defaults(fn=cmd_revoke)

    cp = sub.add_parser("chat", help="streaming chat")
    cp.add_argument("message")
    cp.add_argument("--model")
    cp.set_defaults(fn=cmd_chat)

    ip = sub.add_parser("rag-ingest", help="ingest a document into RAG")
    ip.add_argument("text")
    ip.add_argument("--source")
    ip.add_argument("--chunk-size", type=int, default=800, dest="chunk_size")
    ip.add_argument("--overlap", type=int, default=150)
    ip.set_defaults(fn=cmd_rag_ingest)

    qp = sub.add_parser("rag-query", help="query RAG")
    qp.add_argument("query")
    qp.add_argument("--top-k", type=int, default=4, dest="top_k")
    qp.add_argument("--no-synth", action="store_true", help="skip LLM synthesis, return matches only")
    qp.add_argument("--model")
    qp.add_argument("--source", help="restrict retrieval to a single source")
    qp.set_defaults(fn=cmd_rag_query)

    rc = sub.add_parser("rag-chat", help="streaming RAG answer (retrieve + stream)")
    rc.add_argument("query")
    rc.add_argument("--top-k", type=int, default=4, dest="top_k")
    rc.add_argument("--model")
    rc.add_argument("--source")
    rc.set_defaults(fn=cmd_rag_chat)

    sub.add_parser("rag-sources", help="list ingested sources + chunk counts").set_defaults(fn=cmd_rag_sources)
    sub.add_parser("rag-stats", help="corpus totals (sources, chunks)").set_defaults(fn=cmd_rag_stats)

    dp = sub.add_parser("rag-delete", help="delete all chunks for a source")
    dp.add_argument("--source", required=True)
    dp.set_defaults(fn=cmd_rag_delete)

    return p


def main():
    args = build_parser().parse_args()
    if args.config:
        global CONFIG_PATH, CONFIG_DIR
        CONFIG_PATH = args.config
        CONFIG_DIR = os.path.dirname(args.config) or "."
    args.fn(args)


if __name__ == "__main__":
    main()
