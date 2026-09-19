<#
Stop hook: appends one line to build-log.md per assistant turn, recording
the date/time and the approximate token usage (input + cache-write +
cache-read + output) consumed since the previous turn in this session.

Reads the hook's stdin JSON for session_id/transcript_path, then reads only
the transcript lines added since the last run (tracked per-session in
.claude/build-log-state/<session_id>.txt) so repeated turns don't double-count.
#>

$ErrorActionPreference = 'Stop'

function Get-IntOrZero($value) {
    if ($null -eq $value) { return 0 }
    return [int]$value
}

try {
    $stdin = [Console]::In.ReadToEnd()
    $hookInput = $stdin | ConvertFrom-Json

    $transcriptPath = $hookInput.transcript_path
    $sessionId = $hookInput.session_id
    if (-not $transcriptPath -or -not (Test-Path -LiteralPath $transcriptPath)) {
        exit 0
    }

    $repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..')
    $stateDir = Join-Path $PSScriptRoot '..\build-log-state'
    if (-not (Test-Path -LiteralPath $stateDir)) {
        New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
    }
    $stateFile = Join-Path $stateDir "$sessionId.txt"

    $lines = Get-Content -LiteralPath $transcriptPath
    $totalLines = $lines.Count

    $lastLine = 0
    if (Test-Path -LiteralPath $stateFile) {
        $raw = Get-Content -LiteralPath $stateFile -Raw
        [int]::TryParse($raw.Trim(), [ref]$lastLine) | Out-Null
    }

    if ($totalLines -le $lastLine) {
        exit 0
    }

    $tokenTotal = 0
    for ($i = $lastLine; $i -lt $totalLines; $i++) {
        $line = $lines[$i]
        if (-not $line) { continue }
        try {
            $entry = $line | ConvertFrom-Json
        } catch {
            continue
        }
        if ($entry.type -eq 'assistant' -and $entry.message.usage) {
            $u = $entry.message.usage
            $tokenTotal += Get-IntOrZero $u.input_tokens
            $tokenTotal += Get-IntOrZero $u.cache_creation_input_tokens
            $tokenTotal += Get-IntOrZero $u.cache_read_input_tokens
            $tokenTotal += Get-IntOrZero $u.output_tokens
        }
    }

    Set-Content -LiteralPath $stateFile -Value $totalLines -NoNewline

    $buildLogPath = Join-Path $repoRoot 'build-log.md'
    if ((-not (Test-Path -LiteralPath $buildLogPath)) -or ((Get-Item -LiteralPath $buildLogPath).Length -eq 0)) {
        Set-Content -LiteralPath $buildLogPath -Value "# Build Log" -Encoding utf8
    }

    $now = Get-Date
    $entryLine = "- $($now.ToString('yyyy-MM-dd')) $($now.ToString('HH:mm:ss')) - ~$tokenTotal tokens"
    Add-Content -LiteralPath $buildLogPath -Value $entryLine -Encoding utf8

    exit 0
} catch {
    exit 0
}
