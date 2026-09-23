#!/usr/bin/env python3
"""Static contract for Kaliv VR's renderer and build authority."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "support"))
from source_code import code_of  # noqa: E402

WORKER = code_of(ROOT / "worker/app/body_assets.py")
SERVER = code_of(ROOT / "backend/internal/httpapi/server.go")
BACKEND = code_of(ROOT / "backend/internal/httpapi/body.go")
LOADER = code_of(ROOT / "vr/Assets/Rendering/KalivVrmAvatarLoader.cs")
ENGINE = code_of(ROOT / "vr/Assets/Rendering/KalivVrRenderEngine.cs")
WATCHER = code_of(ROOT / "vr/Assets/Rendering/KalivBodyRevisionWatcher.cs")
STREAM = code_of(ROOT / "vr/Assets/Rendering/KalivBodyFrameStream.cs")
MOTION = code_of(ROOT / "vr/Assets/Rendering/KalivVrmaMotionController.cs")
COMPOSITION = code_of(ROOT / "vr/Assets/Rendering/KalivVrComposition.cs")
SPATIAL = code_of(ROOT / "vr/Assets/Rendering/KalivSpatialTargetRegistry.cs")
PERF = code_of(ROOT / "vr/Assets/Rendering/KalivQuestRenderBudget.cs")
MEDIA = code_of(ROOT / "vr/Assets/Rendering/KalivVrMediaRenderer.cs")
TRACKING = code_of(ROOT / "vr/Assets/Rendering/KalivTrackingOriginCompensator.cs")
RENDERER = code_of(ROOT / "vr/Assets/Rendering/KalivVrmRenderer.cs")
PANEL = code_of(ROOT / "vr/Assets/Scripts/KalivVrPanel.cs")
POINTER = code_of(ROOT / "vr/Assets/Scripts/KalivVrPointer.cs")
BOOTSTRAP = code_of(ROOT / "vr/Assets/Scripts/KalivVrBootstrap.cs")
APP = code_of(ROOT / "vr/Assets/Scripts/KalivVrApp.cs")
BUILD = code_of(ROOT / "vr/Assets/Editor/KalivVrBuild.cs")
ANDROID_MANIFEST = code_of(ROOT / "vr/Assets/Editor/KalivVrAndroidManifest.cs")
TAGS = code_of(ROOT / "vr/ProjectSettings/TagManager.asset")
OPENXR = code_of(ROOT / "vr/Assets/XR/Settings/OpenXR Package Settings.asset")
XR_GENERAL = code_of(ROOT / "vr/Assets/XR/XRGeneralSettingsPerBuildTarget.asset")
FRAME = code_of(ROOT / "vr/Assets/Rendering/KalivBodyRenderFrame.cs")
MANIFEST = code_of(ROOT / "vr/Packages/manifest.json")
PACKAGE_LOCK = code_of(ROOT / "vr/Packages/packages-lock.json")
GRAPHICS = code_of(ROOT / "vr/ProjectSettings/GraphicsSettings.asset")
PLAYER_SETTINGS = code_of(ROOT / "vr/ProjectSettings/ProjectSettings.asset")
QUALITY_SETTINGS = code_of(ROOT / "vr/ProjectSettings/QualitySettings.asset")
EDITOR_BUILD = code_of(ROOT / "vr/ProjectSettings/EditorBuildSettings.asset")
QUEST_OPERATOR = code_of(ROOT / "scripts/run-kaliv-vr-quest-validation.ps1")
GITIGNORE = code_of(ROOT / ".gitignore")

passed = 0
failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


# Renderer-neutral asset boundary.
check(
    '"/active/bodyprint.json"' in WORKER,
    "worker exposes validated bodyprint through the closed body asset router",
)
check(
    '"GET /api/v1/body/active/bodyprint.json"' in SERVER
    and "s.authMW(http.HandlerFunc(s.handleBodyBodyprint))" in SERVER,
    "backend mounts bodyprint behind paired-device bearer auth",
)
check(
    '"/body/active/bodyprint.json"' in BACKEND,
    "backend forwards only the fixed worker bodyprint path",
)

# One exact body/package revision must survive manifest/bodyprint/avatar download.
for needle in (
    "X-BodyRig-Body-ID",
    "X-BodyRig-Package-SHA256",
    "X-BodyRig-Member-SHA256",
    "Sha256(bodyprintBytes)",
    "Sha256(avatarBytes)",
):
    check(needle in LOADER, f"loader carries identity/integrity guard: {needle}")

check(
    'bodyprint.format != "modelrig-bodyprint"' in LOADER
    and "bodyprint.version != 1" in LOADER,
    "loader rejects unknown bodyprint format/version",
)
check(
    "bodyprint.shape.height_scale > 4f" in LOADER
    and "float.IsNaN(bodyprint.shape.height_scale)" in LOADER,
    "height scale is fail-closed against BodyPrint v1 bounds",
)
check(
    'const string prefix = "bodyid-";' in LOADER
    and "prefix.Length + 24" in LOADER
    and "IsLowerHex(manifest.package_sha256, 64)" in LOADER,
    "avatar loader validates canonical BodyRig identity before filesystem caching",
)
check(
    "instance.transform.localScale = Vector3.one * heightScale" in LOADER,
    "accepted BodyPrint height scale is presentation-only",
)
check(
    "AlignFeetToParentFloor(instance)" in LOADER
    and "HumanBodyBones.LeftFoot" in LOADER
    and "HumanBodyBones.RightFoot" in LOADER,
    "accepted humanoid is floor-aligned from foot bones after height scale",
)
check(
    "generation != _loadGeneration" in LOADER and "++_loadGeneration" in LOADER,
    "stale asynchronous avatar revisions cannot win",
)

# Live performed state remains BodyRig authority.
check(
    '"/api/v1/body/frames"' in STREAM and '"Authorization", "Bearer "' in STREAM,
    "live renderer consumes authenticated BodyRig SSE",
)
check(
    "Encoding.UTF8.GetDecoder()" in STREAM
    and "_decoder.GetChars(" in STREAM
    and "Encoding.UTF8.GetString(data, 0, length)" not in STREAM,
    "BodyRig SSE preserves UTF-8 code points across UnityWebRequest chunk boundaries",
)
check(
    "KalivBodyRenderFrame.Parse(json)" in STREAM,
    "SSE payload is validated before renderer apply",
)
check(
    'type != "bodyrig.render_frame" || version != "0.1"' in FRAME,
    "frame parser pins bodyrig.render_frame v0.1",
)
check(
    '"/api/v1/body/active"' in WATCHER
    and "manifest.body_id != _bodyId" in WATCHER
    and "manifest.package_sha256" in WATCHER,
    "revision watcher keys changes on body/package authority",
)
check(
    "RevisionChanged += OnBodyRevisionChanged" in ENGINE
    and "Connect(_baseUrl, _token)" in ENGINE,
    "body/package change triggers a full identity-bound reload",
)

# Authored VRMA supplies body pose only.
check(
    "VrmAnimationImporter" in MOTION and "Vrm10AnimationInstance" in MOTION,
    "VRMA loader uses pinned UniVRM runtime API",
)
check(
    "task.IsCanceled" in MOTION
    and MOTION.index("task.IsCanceled") < MOTION.index("task.Result"),
    "cancelled VRMA task is handled before result dereference",
)
check(
    'new List<string> { "idle" }' in MOTION
    and 'Contains(motionNames, "talk")' in MOTION,
    "only unambiguous idle/talk state motions are auto-mapped",
)
check(
    "ExpressionMap => EmptyExpressions" in MOTION and "LookAt => null" in MOTION,
    "VRMA adapter exposes pose only; BodyRig keeps face/gaze authority",
)
check(
    "[DefaultExecutionOrder(11005)]" in RENDERER,
    "BodyRig overlays execute after UniVRM motion retargeting",
)
check(
    "activeGesture = frame.gesture;" in RENDERER
    and "frame.resolved_gesture" not in RENDERER,
    "renderer keeps ModelRig semantic gesture authoritative over profile replay identity",
)
check(
    '"X-BodyRig-Member-SHA256"' in MOTION
    and '"X-BodyRig-Package-SHA256"' in MOTION,
    "every downloaded VRMA stays digest/revision-bound",
)

# Product composition is explicit and persistent.
for layer in ("KalivBody", "KalivMedia", "KalivUI", "KalivDebug"):
    check(
        layer in TAGS and layer in COMPOSITION,
        f"Unity project pins composition layer {layer}",
    )
check(
    "BodyRoot = CreateRoot" in COMPOSITION
    and "MediaRoot = CreateRoot" in COMPOSITION
    and "UiRoot = CreateRoot" in COMPOSITION
    and "DebugRoot = CreateRoot" in COMPOSITION,
    "composition creates separate body/media/UI/debug roots",
)
check(
    "KalivVrPanel.Create(camera, this, _renderEngine.UiRoot)" in APP
    and "go.transform.SetParent(persistentParent, false)" in PANEL
    and "canvasGo.transform.SetParent(transform, false)" in PANEL,
    "UI controller and canvas share the persistent UI root",
)
check(
    "DontDestroyOnLoad(canvasGo)" not in PANEL,
    "UI canvas does not split lifetime from its controller",
)
check(
    "LayerMask.NameToLayer(KalivVrComposition.UiLayerName)" in POINTER
    and "_interactionMask = 1 << uiLayer" in POINTER
    and "_interactionMask" in POINTER
    and "QueryTriggerInteraction.Ignore" in POINTER,
    "VR pointer raycasts only the committed KalivUI interaction layer",
)
check(
    "InputSystemUIInputModule" in BOOTSTRAP
    and "AssignDefaultActions()" in BOOTSTRAP
    and 'UnityEngine.Object.DontDestroyOnLoad(go);' in BOOTSTRAP,
    "persistent EventSystem carries a runtime UI input module for selected-field keyboard updates",
)
check(
    "ValidateCompositionLayers();" in BUILD and "LayerMask.NameToLayer(layer)" in BUILD,
    "build fails closed if composition layer authority is missing",
)
check(
    "public Transform MediaRoot => _composition?.MediaRoot" in ENGINE,
    "render engine exposes a dedicated SkyPlayer media host",
)
check(
    "SetPresentationRoot(mediaRoot, mediaLayer)" in MEDIA
    and "new MediaSource(url, resumeSeconds)" in MEDIA
    and "Projection.FromHint(formatHint)" in MEDIA,
    "Kaliv media facade binds SkyPlayer playback to the product media root/layer",
)
check(
    "OpenMedia(" in ENGINE
    and "SetMediaFormat(" in ENGINE
    and "PanMedia(" in ENGINE,
    "Kaliv render engine owns the public media presentation facade",
)
check(
    "_mediaRenderer?.Stop();" in ENGINE
    and 'StatusChanged?.Invoke("Renderer afkoblet", false);' in ENGINE,
    "disconnect revokes the active Kaliv media presentation with rig authority",
)
check(
    "OriginShifted += OnOriginShifted" in ENGINE
    and "_mediaRenderer?.ApplyOriginShift(rotationDelta)" in ENGINE
    and "_player.Projection.Geometry != Geometry.Sphere" in MEDIA,
    "tracking-origin rotation is propagated only into immersive media orientation",
)


def openxr_feature_block(feature_id: str) -> str:
    marker = "featureIdInternal: " + feature_id
    index = OPENXR.find(marker)
    if index < 0:
        return ""
    start = OPENXR.rfind("--- !u!114", 0, index)
    end = OPENXR.find("--- !u!114", index)
    if start < 0:
        start = 0
    if end < 0:
        end = len(OPENXR)
    return OPENXR[start:end]


# Quest OpenXR project authority is committed.
for feature in (
    "com.unity.openxr.feature.metaquest",
    "com.unity.openxr.feature.input.oculustouch",
    "dk.ternedal.skyplayer.engine.passthrough",
):
    block = openxr_feature_block(feature)
    check(
        bool(block) and "m_enabled: 1" in block,
        f"OpenXR feature is present and enabled: {feature}",
    )

check(
    "03a3e608f7d397fccd54130a3012f318" in OPENXR
    and "Ternedal.SkyPlayer.Engine::SkyPlayer.Engine.PassthroughFeature" in OPENXR,
    "passthrough setting binds the exact SkyPlayer-Engine feature",
)
check(
    "PassthroughFeature.LogDiagOnce();" in ENGINE,
    "Kaliv runtime surfaces real xrEndFrame passthrough injection evidence",
)
check(
    "com.stashskyplayer.passthrough" not in OPENXR
    and "StashSkyPlayer.PassthroughFeature" not in OPENXR,
    "legacy Skyplayer-local passthrough is absent",
)
check(
    "4c092d04a4d74f443aa067b76eef5b9d" in XR_GENERAL
    and "m_Name: Android Providers" in XR_GENERAL,
    "Android XR management references the committed OpenXR loader",
)
android_settings = XR_GENERAL.find("m_Name: Android Settings")
check(
    android_settings >= 0
    and "m_InitManagerOnStart: 1" in XR_GENERAL[android_settings:],
    "Android XR manager initializes on startup",
)
check(
    "Android XR must initialize on startup." in BUILD,
    "build fails closed if XR startup initialization is disabled",
)
check(
    "ValidateOpenXrAuthority();" in BUILD
    and "RequireEnabledOpenXrFeature" in BUILD,
    "build validates committed Quest/OpenXR feature authority",
)

# Player/package state is committed and immutable during the build.
check(
    "productName: Kaliv VR" in PLAYER_SETTINGS
    and "Android: dk.ternedal.kalivvr" in PLAYER_SETTINGS
    and "bundleVersion: 0.1.0" in PLAYER_SETTINGS,
    "committed PlayerSettings carry Kaliv product identity",
)
check(
    "059f45f5c3ea119468ff3012c348f0c8" not in PLAYER_SETTINGS
    and "e3bc82089e985cd4da88f853225ecdf1" in PLAYER_SETTINGS
    and "88a5359c38cd35641994d333cbdf24c7" in PLAYER_SETTINGS,
    "PlayerSettings retain XR preloads without Skyplayer icon assets",
)
check(
    "scriptingBackend:" in PLAYER_SETTINGS
    and "Android: 1" in PLAYER_SETTINGS
    and "AndroidTargetArchitectures: 2" in PLAYER_SETTINGS
    and "AndroidMinSdkVersion: 29" in PLAYER_SETTINGS,
    "PlayerSettings pin IL2CPP, ARM64 and API 29",
)
check(
    "m_BuildTarget: AndroidPlayer" in PLAYER_SETTINGS
    and "m_APIs: 0b000000" in PLAYER_SETTINGS
    and "m_Automatic: 0" in PLAYER_SETTINGS,
    "Android graphics API is explicitly OpenGLES3",
)
check(
    "ForceInternetPermission: 1" in PLAYER_SETTINGS
    and "PlayerSettings.Android.forceInternetPermission" in BUILD,
    "Android networking permission is committed and build-gated as Require",
)
check(
    "android.permission.INTERNET" in ANDROID_MANIFEST
    and 'usesCleartextTraffic' in ANDROID_MANIFEST,
    "generated Android manifest guarantees INTERNET plus trusted cleartext bootstrap access",
)
check(
    "Android: 2" in QUALITY_SETTINGS and "antiAliasing: 4" in QUALITY_SETTINGS,
    "Android quality authority selects a 4x-MSAA profile",
)
check(
    "m_Scenes: []" in EDITOR_BUILD
    and "com.unity.xr.management.loader_settings" in EDITOR_BUILD
    and "com.unity.xr.openxr.settings4" in EDITOR_BUILD,
    "EditorBuildSettings pin XR config without an authored boot scene",
)

for package_hash in (
    "a4711bbf8c4d10659d3e5568c2e3d7d595005e51",
    "a6c0087624fff26472a8804e7efd4e8e7347c3d7",
):
    check(
        package_hash in PACKAGE_LOCK,
        f"package lock pins exact Git hash {package_hash}",
    )

check(
    "ValidatePackageLockAuthority();" in BUILD
    and "ValidatePlayerSettingsAuthority();" in BUILD,
    "Unity build validates package/player authority",
)
check(
    "PlayerSettings.companyName =" not in BUILD
    and "PlayerSettings.productName =" not in BUILD
    and "QualitySettings.SetQualityLevel" not in BUILD,
    "Unity build does not mutate player/quality settings",
)
check(
    "GeneratedScenePath" in BUILD
    and "CleanupTemporaryBootScene();" in BUILD
    and "AssetDatabase.DeleteAsset(GeneratedScenePath)" in BUILD,
    "code-driven boot scene is temporary and cleaned",
)

# Exact-head physical operator.
check(
    "ValidatePattern" in QUEST_OPERATOR
    and "{40}" in QUEST_OPERATOR
    and "$ExpectedSha" in QUEST_OPERATOR
    and '"rev-parse", "HEAD"' in QUEST_OPERATOR,
    "Quest operator binds execution to an explicit 40-hex Git head",
)
check(
    '"status", "--porcelain=v1", "--untracked-files=all"' in QUEST_OPERATOR
    and QUEST_OPERATOR.count("Assert-CleanTree") >= 3,
    "Quest operator requires clean checkout before and after Unity",
)
check(
    '"6000.4.10f1"' in QUEST_OPERATOR
    and '"Kaliv.VR.EditorTools.KalivVrBuild.BuildAndroid"' in QUEST_OPERATOR,
    "Quest operator invokes exact Unity version and build entrypoint",
)
check(
    "physical_acceptance = $false" in QUEST_OPERATOR
    and "apk_sha256 = $apkSha" in QUEST_OPERATOR,
    "build receipt hashes APK without inventing headset acceptance",
)
check(
    "logcat -c" in QUEST_OPERATOR
    and "logcat -d -v threadtime" in QUEST_OPERATOR
    and "shell pidof $appId" in QUEST_OPERATOR,
    "Quest launch evidence proves a live app process and captures device logs",
)
check(
    "renderer_log_observed = $rendererLogObserved" in QUEST_OPERATOR
    and "passthrough_injection_observed = $passthroughInjectionObserved" in QUEST_OPERATOR
    and "[Passthrough] xrEndFrame underlay injecting OK" in QUEST_OPERATOR,
    "Quest receipt records renderer/passthrough evidence without upgrading physical acceptance",
)
check(
    "adb_device_model = $deviceModel" in QUEST_OPERATOR
    and "android_version = $androidVersion" in QUEST_OPERATOR
    and "app_pid = $appPid" in QUEST_OPERATOR,
    "Quest receipt records bounded device/runtime evidence",
)
check(
    "/validation/kaliv-vr-quest-logcat.txt" in GITIGNORE
    and "/validation/kaliv-vr-quest-latest.json" in GITIGNORE
    and "/validation/kaliv-vr-unity-build.log" in GITIGNORE,
    "Quest validation evidence cannot dirty the exact-head checkout",
)

# Renderer-neutral spatial targets resolve only in the Quest scene.
check(
    '"object:"' in SPATIAL
    and '"world:"' in SPATIAL
    and "Dictionary<string, Transform>" in SPATIAL,
    "spatial registry maps semantic object/world tokens to local transforms",
)
check(
    "spatialTargets.TryResolve(target, out Transform spatialTarget)" in RENDERER,
    "VRM gaze resolves object/world targets through local registry",
)
check(
    "RegisterObjectTarget" in ENGINE and "RegisterWorldTarget" in ENGINE,
    "render engine exposes explicit local spatial registration",
)
check(
    "HumanBodyBones" not in SPATIAL and "api/v1" not in SPATIAL,
    "spatial registry carries neither bone nor network authority",
)

# Static Quest budget is only a warning, never a physical performance PASS.
check(
    "Quest2RecommendedSceneDrawCalls = 100" in PERF
    and "Quest2RecommendedSceneTriangles = 750_000" in PERF,
    "avatar soft guard pins current Quest 2 scene guidance",
)
check(
    "avatar alone exceeds current Quest 2 whole-scene guidance" in PERF
    and "device profiling still required" in PERF,
    "soft guard distinguishes static sanity from physical profiling",
)
check(
    "KalivQuestRenderBudget.Log(instance.gameObject)" in ENGINE,
    "accepted avatar is measured on entry to the render scene",
)
check(
    "DisplayChanged += OnMediaDisplayChanged" in ENGINE
    and 'KalivQuestRenderBudget.LogScene(gameObject, "avatar-loaded")' in ENGINE
    and "KalivQuestRenderBudget.LogScene(" in ENGINE,
    "renderer-scene budget is re-sampled when avatar/media composition changes",
)
check(
    "UI/compositor/passthrough cost is not included" in PERF
    and "device profiling remains mandatory" in PERF,
    "renderer-scene snapshot cannot masquerade as physical Quest performance acceptance",
)

# Tracking-origin shifts move presentation, never the HMD/XR Origin.
check(
    "trackingOriginUpdated += OnTrackingOriginUpdated" in TRACKING
    and "trackingOriginUpdated -= OnTrackingOriginUpdated" in TRACKING,
    "tracking-origin event lifecycle is balanced",
)
check(
    "currentRotation * Quaternion.Inverse(_previousRotation)" in TRACKING
    and "currentPosition + rotationDelta * oldRelative" in TRACKING,
    "origin compensation applies the camera rigid pose delta",
)
check(
    "Time.frameCount <= _dirtyFrame" in TRACKING
    and "_dirtyFrame = Time.frameCount" in TRACKING
    and "return;" in TRACKING,
    "origin compensation preserves the pre-event HMD pose through the event frame",
)
check(
    "Time.frameCount <= _dirtyFrame + 3" in TRACKING
    and "settledDelta" in TRACKING,
    "origin compensation tolerates runtimes whose camera pose settles after the origin event",
)
check(
    "XROrigin" not in TRACKING,
    "tracking compensator never reconfigures the XR Origin",
)
check(
    "_trackingOrigin.Initialize(_camera, transform)" in ENGINE,
    "origin shifts apply to the persistent Kaliv composition root",
)

# Renderer-specific vocabulary must not leak upstream.
for forbidden in ('"HumanBodyBones"', '"SetBone"', '"joint"', '"bone_path"'):
    check(
        forbidden not in STREAM and forbidden not in WATCHER,
        f"network/revision layers do not emit renderer command {forbidden}",
    )

check(
    "#v0.131.2" in MANIFEST and "com.vrmc.vrm" in MANIFEST,
    "UniVRM is exact-tag pinned",
)
check(
    "e0edbf68d81d1f340ae8b110086b7063" in GRAPHICS
    and "8c17b56f4bf084c47872edcb95237e4a" in GRAPHICS,
    "MToon10 and UniUnlit are committed runtime shader authority",
)

print(f"\nkaliv vr renderer contract: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)
