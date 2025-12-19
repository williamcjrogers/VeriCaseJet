# Bootstrap SSH config + known_hosts for VeriCase EC2 (Windows)
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\vericase\ops\setup-ssh.ps1

param(
    [string]$SshHost = "18.175.232.87",
    [string]$User = "ec2-user",
    [int]$Port = 22,
    [string]$KeyPath = $(if ($env:SSH_KEY_PATH) { $env:SSH_KEY_PATH } else { "$env:USERPROFILE\.ssh\VeriCase-Safe.pem" }),
    [string]$KnownHostsPath = "$env:USERPROFILE\.ssh\known_hosts",
    [string]$SshConfigAlias = "vericase-ec2",
    [switch]$SkipSshConfig
)

$ErrorActionPreference = "Stop"

$sshDir = Join-Path $env:USERPROFILE ".ssh"
New-Item -ItemType Directory -Force -Path $sshDir | Out-Null

if (-not (Test-Path $KeyPath)) {
    throw "SSH key not found: $KeyPath (set SSH_KEY_PATH or place key at the default path)"
}

$resolvedKeyPath = (Resolve-Path $KeyPath).Path

if (-not $SkipSshConfig) {
    $configPath = Join-Path $sshDir "config"
    $existing = ""
    if (Test-Path $configPath) {
        $existing = Get-Content $configPath -Raw
    }

    $aliasRegex = "(?m)^\s*Host\s+" + [regex]::Escape($SshConfigAlias) + "\s*$"
    if ($existing -notmatch $aliasRegex) {
        $block = @"

Host $SshConfigAlias
HostName $SshHost
    User $User
    Port $Port
    IdentityFile $resolvedKeyPath
"@
        Add-Content -Path $configPath -Value $block -Encoding UTF8
        Write-Host "Added SSH config alias '$SshConfigAlias' to: $configPath"
    } else {
        Write-Host "SSH config alias '$SshConfigAlias' already exists in: $configPath"
    }
}

Write-Host "Priming known_hosts at: $KnownHostsPath"
New-Item -ItemType File -Force -Path $KnownHostsPath | Out-Null

function Invoke-PrimeHostKey([string]$strictOption) {
    $args = @(
        "-i", $resolvedKeyPath,
        "-p", "$Port",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=10",
        "-o", "UserKnownHostsFile=$KnownHostsPath",
        "-o", "StrictHostKeyChecking=$strictOption",
        "$User@$SshHost",
        "exit"
    )

    & ssh @args | Out-Null
    return ($LASTEXITCODE -eq 0)
}

if (Invoke-PrimeHostKey "accept-new") {
    Write-Host "known_hosts updated (StrictHostKeyChecking=accept-new)."
} else {
    Write-Warning "Could not prime host key with accept-new (older OpenSSH?)."
    Write-Warning "Falling back to StrictHostKeyChecking=no to populate known_hosts (TOFU)."
    if (-not (Invoke-PrimeHostKey "no")) {
        throw "Failed to connect via SSH to $User@$SshHost on port $Port."
    }
    Write-Host "known_hosts updated (fallback). Consider verifying the host key fingerprint out-of-band."
}

Write-Host "Done. Test:"
Write-Host "  ssh $SshConfigAlias"
Write-Host "Ops scripts in this repo verify host keys via known_hosts (StrictHostKeyChecking=yes)."
