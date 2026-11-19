# Claude Island status line for Windows (PowerShell 5.1 or later).
#
# Claude Code runs the status line command with a JSON document on stdin (model, context window,
# plan limits, cost...). This script saves that JSON, unchanged, to
#   ~/.claude/island/<session_id>.json
# where Claude Island reads it, then prints a short status line (model + context %).
# It never throws: on any error it still prints something and exits 0.
#
# settings.json:
#   "statusLine": { "type": "command",
#     "command": "powershell -NoProfile -ExecutionPolicy Bypass -File C:\\path\\to\\island-statusline.ps1" }

$ErrorActionPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false } catch {}

$raw = ''
try {
    $reader = New-Object System.IO.StreamReader([Console]::OpenStandardInput(), (New-Object System.Text.UTF8Encoding $false))
    $raw = $reader.ReadToEnd()
} catch {}

$d = $null
try { $d = $raw | ConvertFrom-Json -ErrorAction Stop } catch {}

# Save the raw JSON for the widget (atomic: write a temp file, then rename over the target).
try {
    $sid = [string]$d.session_id
    if ($sid -and $sid -match '^[A-Za-z0-9._-]+$') {
        $dir = Join-Path $HOME '.claude\island'
        if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        $target = Join-Path $dir ($sid + '.json')
        $tmp = Join-Path $dir ($sid + '.json.' + $PID + '.tmp')
        [System.IO.File]::WriteAllText($tmp, $raw, (New-Object System.Text.UTF8Encoding $false))
        Move-Item -LiteralPath $tmp -Destination $target -Force -ErrorAction Stop
    }
} catch {
    try { if ($tmp) { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue } } catch {}
}

# A minimal status line of its own: "<model> | ctx 42%".
try {
    $parts = @()
    $model = [string]$d.model.display_name
    if ($model) { $parts += $model }
    $cw = $d.context_window
    if ($cw) {
        $pct = $cw.used_percentage
        if ($null -eq $pct -and $cw.current_usage -and [double]$cw.context_window_size -gt 0) {
            $u = $cw.current_usage
            $used = [double]$u.input_tokens + [double]$u.cache_creation_input_tokens + [double]$u.cache_read_input_tokens
            $pct = $used / [double]$cw.context_window_size * 100
        }
        if ($null -ne $pct) { $parts += ('ctx {0:0}%' -f [double]$pct) }
    }
    if ($parts.Count -eq 0) { $parts += 'Claude Code' }
    Write-Output ($parts -join ' | ')
} catch {
    Write-Output 'Claude Code'
}
exit 0
