param(
    [string]$Url = '',
    [ValidateSet('msedge', 'chrome')]
    [string]$Browser = 'msedge',
    [string]$SessionFile = '',
    [string]$ProfileDir = '',
    [switch]$NoLaunchCodex
)

$ErrorActionPreference = 'Stop'
$pluginRoot = Split-Path -Parent $PSScriptRoot

function Find-Uv {
    $uvCommand = Get-Command uv -ErrorAction SilentlyContinue
    if ($uvCommand) { return $uvCommand.Source }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    $pythonArguments = @()
    if (-not $pythonCommand) {
        $pythonCommand = Get-Command py -ErrorAction SilentlyContinue
        $pythonArguments = @('-3')
    }
    if (-not $pythonCommand) {
        throw 'Install Python 3.11 or newer, or install uv, then run this launcher again.'
    }
    $moduleCheck = @($pythonArguments) + @('-c', 'import importlib.util; raise SystemExit(0 if importlib.util.find_spec(''uv'') else 1)')
    & $pythonCommand.Source @moduleCheck | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Installing uv into your Python user environment...'
        $installArguments = @($pythonArguments) + @('-m', 'pip', 'install', '--user', 'uv')
        & $pythonCommand.Source @installArguments | Out-Host
        if ($LASTEXITCODE -ne 0) { throw 'uv installation failed. Install uv and run again.' }
    }
    $findArguments = @($pythonArguments) + @('-c', 'import uv; print(uv.find_uv_bin())')
    $uvPath = (& $pythonCommand.Source @findArguments | Select-Object -Last 1)
    if ($LASTEXITCODE -ne 0 -or -not $uvPath -or -not (Test-Path -LiteralPath $uvPath)) {
        throw 'Cannot locate uv. Run: python -m pip install --user uv'
    }
    return $uvPath.Trim()
}

$previousPath = $env:Path
$savedVariables = @{}
$authVariableNames = @(
    'OPENLIST_TOKEN', 'OPENLIST_TOKEN_FILE', 'OPENLIST_USERNAME',
    'OPENLIST_PASSWORD', 'OPENLIST_PASSWORD_FILE', 'OPENLIST_OTP_CODE'
)
foreach ($variableName in $authVariableNames) {
    $savedVariables[$variableName] = [Environment]::GetEnvironmentVariable($variableName, 'Process')
}

try {
    if (-not $NoLaunchCodex) {
        $codexCommand = Get-Command codex -ErrorAction SilentlyContinue
        if (-not $codexCommand) { throw 'Codex CLI was not found. Install Codex CLI and run again.' }
    }
    $uvPath = Find-Uv
    $env:Path = (Split-Path -Parent $uvPath) + [IO.Path]::PathSeparator + $env:Path

    if (-not $Url) {
        $Url = Read-Host 'OpenList URL (Enter = http://127.0.0.1:5244)'
        if (-not $Url) { $Url = 'http://127.0.0.1:5244' }
    }
    if (-not $PSBoundParameters.ContainsKey('Browser')) {
        $browserChoice = Read-Host 'Browser: 1 = Edge, 2 = Chrome (Enter = Edge)'
        if ($browserChoice -eq '2') { $Browser = 'chrome' }
        elseif ($browserChoice -and $browserChoice -ne '1') { throw 'Choose 1 for Edge or 2 for Chrome.' }
    }

    if (-not $NoLaunchCodex) {
        Write-Host 'Installing this OpenList plugin version into Codex...'
        # Replace only this project's marketplace; this also handles a moved ZIP folder.
        $previousErrorPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue'
            & $codexCommand.Source plugin marketplace remove heavenyygq-openlist *> $null
        } finally { $ErrorActionPreference = $previousErrorPreference }
        & $codexCommand.Source plugin marketplace add $pluginRoot
        if ($LASTEXITCODE -ne 0) { throw 'Cannot register the OpenList marketplace.' }
        & $codexCommand.Source plugin add openlist@heavenyygq-openlist
        if ($LASTEXITCODE -ne 0) { throw 'Cannot install the OpenList plugin.' }
    }

    foreach ($variableName in $authVariableNames) {
        [Environment]::SetEnvironmentVariable($variableName, $null, 'Process')
    }
    $linkArguments = @('--project', $pluginRoot, 'run', '--group', 'browser', '--locked',
        'openlist-codex-link', '--url', $Url, '--browser', $Browser)
    if (-not $NoLaunchCodex) { $linkArguments += '--launch-codex' }
    if ($SessionFile) { $linkArguments += @('--session-file', $SessionFile) }
    if ($ProfileDir) { $linkArguments += @('--profile-dir', $ProfileDir) }

    Write-Host 'An associated OpenList browser window will open.'
    Write-Host 'Log in there. The plugin will use that login automatically.'
    Write-Host 'This window has a dedicated profile, separate from your normal browser.'
    Write-Host 'Keep the window open to synchronize login changes and logout.'
    & $uvPath @linkArguments
    if ($LASTEXITCODE -ne 0) { throw 'The OpenList browser link stopped with an error.' }
} finally {
    $env:Path = $previousPath
    foreach ($variableName in $authVariableNames) {
        [Environment]::SetEnvironmentVariable($variableName, $savedVariables[$variableName], 'Process')
    }
}
