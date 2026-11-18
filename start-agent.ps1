param([switch]$Live, [switch]$Offline, [switch]$Check, [string]$EnvFile, [string]$Runtime, [int]$Port = 8021)
$ErrorActionPreference = 'Stop'
$agentRoot = $PSScriptRoot
$agentPython = Join-Path $agentRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $agentPython)) {
    throw '请先在项目目录执行：python -m venv .venv，然后 ./.venv/Scripts/python.exe -m pip install -r backend/requirements-agent.txt'
}
Push-Location $agentRoot
try {
    $agentArgs = @('backend/scripts/run_agent_local.py', '--port', "$Port")
    if ($Live) { $agentArgs += '--live' }
    if ($Offline) { $agentArgs += '--offline' }
    if ($Check) { $agentArgs += '--check' }
    if ($EnvFile) { $agentArgs += @('--env-file', $EnvFile) }
    if ($Runtime) { $agentArgs += @('--runtime', $Runtime) }
    & $agentPython @agentArgs
} finally { Pop-Location }
