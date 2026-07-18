from __future__ import annotations

import inspect
import os
import shutil
import tempfile
from pathlib import Path

from pydantic import ValidationError

from app.browser_use_adapter import (
    READ_ONLY_EXCLUDED_ACTIONS,
    SUPPORTED_BROWSER_USE_VERSION,
    BrowserUseReadOnlyNavigateAction,
    BrowserUseResearchOutput,
    build_read_only_browser_profile,
    load_browser_use_bindings,
    lock_read_only_tools,
)

passed = failed = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


bindings = load_browser_use_bindings()
check(bindings.version == SUPPORTED_BROWSER_USE_VERSION, "exact Browser Use version loads")
check(bindings.runtime_validated, "real bindings are marked runtime-validated")
for name in (
    "ANONYMIZED_TELEMETRY",
    "BROWSER_USE_CLOUD_SYNC",
    "BROWSER_USE_VERSION_CHECK",
    "BROWSER_USE_SETUP_LOGGING",
):
    check(os.environ.get(name) == "false", f"runtime forces {name}=false before import")

agent_parameters = inspect.signature(bindings.agent_factory).parameters
for parameter in (
    "task",
    "llm",
    "browser_profile",
    "browser_session",
    "tools",
    "output_model_schema",
    "use_vision",
    "sensitive_data",
    "available_file_paths",
    "max_actions_per_step",
    "use_judge",
    "enable_signal_handler",
):
    check(parameter in agent_parameters, f"Agent exposes {parameter}")

tools_parameters = inspect.signature(bindings.tools_factory).parameters
check("exclude_actions" in tools_parameters, "Tools exposes exclude_actions")
check("display_files_in_done_text" in tools_parameters, "Tools exposes display_files_in_done_text")

profile = build_read_only_browser_profile(
    bindings,
    ["example.com", "*.example.com"],
)

download_path = Path(profile.downloads_path).expanduser().resolve(strict=True)
user_data_path = Path(profile.user_data_dir).expanduser().resolve(strict=True)
temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
try:
    check(profile.headless is True, "profile is headless")
    check(profile.allowed_domains == ["example.com", "*.example.com"], "profile keeps the exact allowlist")
    check(profile.storage_state is None, "profile imports no cookie or storage state")
    check(profile.keep_alive is False, "profile is single-use")
    check(profile.block_ip_addresses is True, "profile blocks direct IP navigation")
    check(profile.enable_default_extensions is False, "default extensions are disabled")
    check(profile.accept_downloads is False, "browser context refuses downloads")
    check(profile.permissions == [], "browser context grants no permissions")
    check(profile.auto_download_pdfs is False, "automatic PDF downloads are disabled")
    check(profile.captcha_solver is False, "captcha side-effect service is disabled")
    check(profile.cross_origin_iframes is False, "cross-origin iframe processing is disabled")
    check(profile.use_cloud is False, "cloud browser fallback is disabled")
    check(profile.disable_security is False, "Chromium security is never disabled")
    check(profile.demo_mode is False, "browser demo overlay is disabled")
    check(profile.record_har_path is None, "HAR recording is disabled")
    check(profile.record_video_dir is None, "video recording is disabled")
    check(profile.traces_dir is None, "Playwright trace recording is disabled")

    check(download_path.parent == temp_root, "download quarantine is directly under system temp")
    check(download_path.name.startswith("browser-use-downloads-"), "download quarantine uses Browser Use's unique prefix")
    check(download_path.is_dir(), "download quarantine exists before browser startup")
    check(next(download_path.iterdir(), None) is None, "download quarantine starts empty")

    check(user_data_path.parent == temp_root, "profile quarantine is directly under system temp")
    check(
        user_data_path.name.startswith("browser-use-user-data-dir-"),
        "profile quarantine uses Browser Use's unique prefix",
    )
    check(user_data_path.is_dir(), "profile quarantine exists before browser startup")
    check(next(user_data_path.iterdir(), None) is None, "profile quarantine starts empty")
    check(user_data_path != download_path, "profile and download quarantines are distinct")

    tools = lock_read_only_tools(
        bindings.tools_factory(
            exclude_actions=list(READ_ONLY_EXCLUDED_ACTIONS),
            display_files_in_done_text=False,
        )
    )
    registry = getattr(getattr(tools, "registry", None), "registry", None)
    actions = getattr(registry, "actions", None)
    check(isinstance(actions, dict), "Tools exposes a concrete action registry")
    action_names = set(actions or {})
    for denied in READ_ONLY_EXCLUDED_ACTIONS:
        check(denied not in action_names, f"action {denied} is absent")
    for required in ("navigate", "go_back", "wait", "scroll", "extract", "done"):
        check(required in action_names, f"read-only action {required} remains available")

    navigate_model = actions["navigate"].param_model
    check(
        navigate_model is BrowserUseReadOnlyNavigateAction,
        "navigate uses ModelRig's current-tab-only parameter model",
    )
    check(
        navigate_model(url="https://example.com/").new_tab is False,
        "navigate defaults to the current tab",
    )
    try:
        navigate_model(url="https://example.com/", new_tab=True)
    except ValidationError:
        check(True, "navigate(new_tab=true) is structurally rejected")
    else:
        check(False, "navigate(new_tab=true) is structurally rejected")

    from browser_use.agent.views import AgentHistoryList

    for member in ("urls", "number_of_steps", "is_successful", "has_errors", "structured_output"):
        check(hasattr(AgentHistoryList, member), f"history exposes {member}")
    check(
        issubclass(BrowserUseResearchOutput, __import__("pydantic").BaseModel),
        "structured output remains a Pydantic model",
    )
finally:
    for path in (download_path, user_data_path):
        shutil.rmtree(path, ignore_errors=False)

check(not download_path.exists(), "runtime-contract smoke removes its download quarantine")
check(not user_data_path.exists(), "runtime-contract smoke removes its profile quarantine")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
