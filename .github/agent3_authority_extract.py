from __future__ import annotations

import traceback
from pathlib import Path


SOURCE = Path('/tmp/agent3-builder.yml')
OUTPUT = Path('/tmp/agent3-authority-patch.py')
DIAGNOSTIC = Path('/tmp/agent3-extract.log')


def splice_between(program: str, start_marker: str, end_marker: str, replacement: str, *, after: int = 0) -> str:
    start = program.index(start_marker, after)
    end = program.index(end_marker, start)
    return program[:start] + replacement + program[end:]


def main() -> int:
    source = SOURCE.read_text(encoding='utf-8')
    marker = "          python3 - <<'PY'\n"
    start = source.index(marker) + len(marker)
    end = source.index("\n          PY\n", start)
    lines = source[start:end].splitlines()
    program = "\n".join(line[10:] if line.startswith("          ") else line for line in lines) + "\n"

    api_replacement = '''    def start_explicit(req: ExplicitStartReq) -> dict[str, Any]:
        """Exercise the low-level adapter in tests without exposing it in production."""
        caps = capability_provider(req, adapter)
        if not req.plan:
            raise HTTPException(status_code=422, detail="the test fixture requires a plan")
        if not req.tools:
            raise HTTPException(status_code=400, detail="an explicit tool plan requires tools=true")
        request = TurnRequest(
            message=req.message,
            mode=req.mode,
            tools=req.tools,
            rag=req.rag,
            has_image=req.has_image,
            voice=req.voice,
            allow_rag_cloud=req.allow_rag_cloud,
            auto_cloud_fallback=req.auto_cloud_fallback,
            conversation_id=req.conversation_id,
        )
        route = orchestrator.router.route(request, caps)
        if route.kind in {RouteKind.UNAVAILABLE, RouteKind.ASK_BEFORE_DOWNGRADE}:
            run = start_steps(
                request,
                caps,
                [],
                proactive=req.proactive,
                allow_private_cloud=req.allow_private_cloud,
                review_reads=req.review_reads,
            )
            return response(run)
        try:
            calls = [PlannedToolCall(step.tool, step.args) for step in req.plan]
            steps = adapter.build_steps(calls, route, req.conversation_id)
            run = start_steps(
                request,
                caps,
                steps,
                proactive=req.proactive,
                allow_private_cloud=req.allow_private_cloud,
                review_reads=req.review_reads,
            )
        except Agent3PlanError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return response(run)

    if allow_client_plans:
        router.add_api_route(
            "/runs",
            start_explicit,
            methods=["POST"],
            include_in_schema=False,
        )

    @router.post("/runs/{run_id}/retry")
    def retry(run_id: str, req: RetryReq) -> dict[str, Any]:
        original = orchestrator.store.load(run_id)
        if original is None:
            raise HTTPException(status_code=404, detail="original run not found")
        caps = capability_provider(req, adapter)
        request = TurnRequest(
            message=original.request.message,
            mode=original.request.mode,
            tools=original.request.tools,
            rag=original.request.rag,
            has_image=original.request.has_image,
            voice=original.request.voice,
            allow_rag_cloud=original.request.allow_rag_cloud,
            auto_cloud_fallback=original.request.auto_cloud_fallback,
            retry_of_run_id=original.id,
            original_route=original.route.kind,
            conversation_id=original.request.conversation_id,
        )
        original_review = read_review(original.id)["enabled"]
        run = start_steps(
            request,
            caps,
            _clone_steps(original),
            proactive=original.proactive,
            allow_private_cloud=original.allow_private_cloud,
            review_reads=bool(original_review),
        )
        return response(run)

'''
    api_scope = program.index("api_path = ROOT / 'worker/app/agent3/api.py'")
    api_start = program.index('replacement =', api_scope)
    api_end = program.index('api_path.write_text', api_start)
    program = program[:api_start] + f'replacement = {api_replacement!r}\n' + program[api_end:]

    android_anchor = '''    fun events(runId: String): List<Event> {
        val arr = get("/api/v1/experimental/agent3/runs/$runId/events")
            .optJSONArray("events") ?: JSONArray()
        return buildList {
            for (i in 0 until arr.length()) {
                val e = arr.optJSONObject(i) ?: continue
                add(Event(e.optDouble("ts"), e.optString("kind"), e.opt("payload")?.toString().orEmpty()))
            }
        }
    }

'''
    android_retry = '''    fun retry(runId: String, cloudReady: Boolean = false): Run {
        val payload = JSONObject().put("cloud_ready", cloudReady)
        val root = post("/api/v1/experimental/agent3/runs/$runId/retry", payload)
        return parseRun(root.requireObject("run"))
    }

'''
    android_start = program.index('android_anchor =')
    android_end = program.index("replace_once(\n    'android/app/src/main/java/dk/ternedal/modelrig/net/Agent3Client.kt'", android_start)
    android_source = f'android_anchor = {android_anchor!r}\nandroid_retry = android_anchor + {android_retry!r}\n'
    program = program[:android_start] + android_source + program[android_end:]

    desktop_path = 'desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/net/Agent3Client.kt'
    desktop_models_old = '''@Serializable
private data class ConfirmRequest(
    @SerialName("step_id") val stepId: String,
    val decision: String,
    val digest: String,
)
'''
    desktop_models_new = '''@Serializable
private data class ConfirmRequest(
    @SerialName("step_id") val stepId: String,
    val decision: String,
    val digest: String,
)

@Serializable
private data class RetryRequest(
    @SerialName("cloud_ready") val cloudReady: Boolean = false,
)
'''
    desktop_events_old = '''    fun events(runId: String): List<Agent3Event> =
        decode<EventsEnvelope>(get("/api/v1/experimental/agent3/runs/$runId/events")).events

'''
    desktop_events_new = '''    fun events(runId: String): List<Agent3Event> =
        decode<EventsEnvelope>(get("/api/v1/experimental/agent3/runs/$runId/events")).events

    fun retry(runId: String, cloudReady: Boolean = false): Agent3Run =
        decode<Agent3RunEnvelope>(
            post(
                "/api/v1/experimental/agent3/runs/$runId/retry",
                json.encodeToString(RetryRequest(cloudReady)),
            )
        ).run

'''
    desktop_start = program.index("replace_once(\n    'desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/net/Agent3Client.kt'", android_end)
    desktop_end = program.index('# --- test-only explicit route opt-in', desktop_start)
    desktop_source = (
        f'replace_once({desktop_path!r}, {desktop_models_old!r}, {desktop_models_new!r})\n'
        f'replace_once({desktop_path!r}, {desktop_events_old!r}, {desktop_events_new!r})\n\n'
    )
    program = program[:desktop_start] + desktop_source + program[desktop_end:]

    compile(program, str(OUTPUT), 'exec')
    OUTPUT.write_text(program, encoding='utf-8')
    DIAGNOSTIC.write_text(
        f'source_bytes={len(source.encode("utf-8"))}\nprogram_bytes={len(program.encode("utf-8"))}\nstatus=ok\n',
        encoding='utf-8',
    )
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        detail = traceback.format_exc()
        DIAGNOSTIC.write_text(detail, encoding='utf-8')
        print(detail, end='')
        raise
