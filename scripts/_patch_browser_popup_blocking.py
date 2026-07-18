#!/usr/bin/env python3
from pathlib import Path


def exact(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one target, found {count}")
    return text.replace(old, new)


adapter_path = Path("worker/app/browser_use_adapter.py")
adapter = adapter_path.read_text(encoding="utf-8")
adapter = exact(
    adapter,
    '''            "browser_profile",
            "tools",''',
    '''            "browser_profile",
            "browser_session",
            "tools",''',
    "Agent browser_session contract",
)
adapter = exact(
    adapter,
    '''        "downloads_path",
        "accept_downloads",''',
    '''        "downloads_path",
        "ignore_default_args",
        "accept_downloads",''',
    "profile ignore_default_args contract",
)
adapter = exact(
    adapter,
    '''    if bindings.runtime_validated:
        expected = {''',
    '''    if bindings.runtime_validated:
        ignored_default_args = list(getattr(profile, "ignore_default_args", ()) or ())
        if "--disable-popup-blocking" not in ignored_default_args:
            ignored_default_args.append("--disable-popup-blocking")
            profile.ignore_default_args = ignored_default_args
        expected = {''',
    "popup blocker activation",
)
adapter = exact(
    adapter,
    '''        if list(getattr(profile, "permissions", ())) != []:
            raise BrowserBackendUnavailable(
                "browser-use profile retained browser permissions"
            )''',
    '''        if "--disable-popup-blocking" not in list(
            getattr(profile, "ignore_default_args", ()) or ()
        ):
            raise BrowserBackendUnavailable(
                "browser-use profile disabled Chromium popup blocking"
            )
        if list(getattr(profile, "permissions", ())) != []:
            raise BrowserBackendUnavailable(
                "browser-use profile retained browser permissions"
            )''',
    "popup blocker validation",
)
adapter = exact(
    adapter,
    '''                except BrowserUseNetworkGuardError as exc:
                    guard_error = BrowserBackendError(
                        "browser request guard cleanup failed"
                    )
                    guard_error.__cause__ = exc''',
    '''                except BrowserUseNetworkGuardError:
                    guard_error = BrowserBackendError(
                        "browser request guard cleanup failed"
                    )''',
    "cleanup error normalization",
)
adapter_path.write_text(adapter, encoding="utf-8")

runtime_path = Path("tests/worker_browser_use_runtime_guard.py")
runtime = runtime_path.read_text(encoding="utf-8")
runtime = exact(
    runtime,
    '''check(clean_runtime.profile_kwargs["traces_dir"] is None, "trace recording is disabled")
check(clean_runtime.profile_kwargs["auto_download_pdfs"] is False, "automatic PDF downloads are disabled")''',
    '''check(clean_runtime.profile_kwargs["traces_dir"] is None, "trace recording is disabled")
check(
    "--disable-popup-blocking" in clean_runtime.agent.browser_session.__class__.__name__
    or "--disable-popup-blocking" in getattr(
        clean_runtime,
        "profile_ignore_default_args",
        (),
    ),
    "validated profile restores Chromium popup blocking",
)
check(clean_runtime.profile_kwargs["auto_download_pdfs"] is False, "automatic PDF downloads are disabled")''',
    "runtime popup assertion placeholder",
)
# The profile object is returned through the fake agent; expose its locked launch args.
runtime = exact(
    runtime,
    '''        profile_fields.update(
            downloads_path=download_path,
            user_data_dir=user_data_path,
        )
        return SimpleNamespace(**profile_fields)''',
    '''        profile_fields.update(
            downloads_path=download_path,
            user_data_dir=user_data_path,
        )
        profile = SimpleNamespace(**profile_fields)
        self.profile_object = profile
        return profile''',
    "fake profile capture",
)
runtime = exact(
    runtime,
    '''        self.profile_kwargs = None
        self.tools_kwargs = None''',
    '''        self.profile_kwargs = None
        self.profile_object = None
        self.tools_kwargs = None''',
    "fake profile field",
)
runtime = runtime.replace(
    '''check(
    "--disable-popup-blocking" in clean_runtime.agent.browser_session.__class__.__name__
    or "--disable-popup-blocking" in getattr(
        clean_runtime,
        "profile_ignore_default_args",
        (),
    ),
    "validated profile restores Chromium popup blocking",
)''',
    '''check(
    "--disable-popup-blocking" in clean_runtime.profile_object.ignore_default_args,
    "validated profile restores Chromium popup blocking",
)''',
)
runtime_path.write_text(runtime, encoding="utf-8")

Path("scripts/_patch_browser_popup_blocking.py").unlink()
print("patched Browser Use popup-blocking contract")
