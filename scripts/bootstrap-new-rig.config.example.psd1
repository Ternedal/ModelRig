@{
    # Root used for source checkouts, ModelRig appliance runtime and bootstrap logs.
    InstallRoot = 'C:\Rig'

    # BodyRig V1 installation authority. Keep pinned unless BodyRig explicitly
    # publishes a newer installation authority.
    BodyRigRef = '76c64a9546238663dedf750a1da4a230cc1e7fa4'
    WslDistribution = 'Ubuntu-22.04'

    # Baseline models declared by the current ModelRig/VoiceRig defaults.
    # Add/remove local models here if the old rig has a different deliberate set.
    OllamaModels = @(
        'nomic-embed-text'
        'qwen2.5-coder:7b'
        'gemma3:12b'
    )

    # Before the extra RTX 3060 is moved, keep this at the number of NVIDIA GPUs
    # currently installed in the new rig. After the move, raise it and re-run
    # -Phase Validate.
    MinimumGpuCount = 1

    # BodyRig cannot redistribute these assets. Fill them in when ready.
    # SmplModelPath and SmplxSource are Windows paths.
    # DiffusionModel is a path inside the selected WSL distribution.
    SmplModelPath = ''
    SmplxSource = ''
    DiffusionModel = ''
}
