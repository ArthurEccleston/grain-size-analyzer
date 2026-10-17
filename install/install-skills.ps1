# Install Arthur's SEM / mechanical skills from GitHub.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File install-skills.ps1
#   powershell -ExecutionPolicy Bypass -File install-skills.ps1 -SkillsDir C:\path\to\skills
param(
    [string]$SkillsDir = $(if ($env:SKILLS_DIR) { $env:SKILLS_DIR } else { Join-Path $HOME ".claude\skills" })
)

$ErrorActionPreference = "Stop"
$repos = @(
    @{ Repo = "instron-tensile-analysis-skill"; Name = "instron-tensile-analysis" },
    @{ Repo = "grain-size-analyzer"; Name = "grain-size" }
)

New-Item -ItemType Directory -Force -Path $SkillsDir | Out-Null
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("skills-install-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null

try {
    foreach ($item in $repos) {
        $repo = $item.Repo
        $name = $item.Name
        $work = Join-Path $tmp $repo
        Write-Host "Installing $name from github.com/ArthurEccleston/$repo"

        if (Get-Command git -ErrorAction SilentlyContinue) {
            git clone --depth 1 "https://github.com/ArthurEccleston/$repo.git" $work
        } else {
            $zip = Join-Path $tmp "$repo.zip"
            $url = "https://github.com/ArthurEccleston/$repo/archive/refs/heads/main.zip"
            Invoke-WebRequest -Uri $url -OutFile $zip
            Expand-Archive -Path $zip -DestinationPath $work
            $work = (Get-ChildItem $work | Select-Object -First 1).FullName
        }

        $target = Join-Path $SkillsDir $name
        if (Test-Path $target) { Remove-Item -Recurse -Force $target }
        Copy-Item -Recurse -Force $work $target
        Remove-Item -Recurse -Force (Join-Path $target ".git") -ErrorAction SilentlyContinue

        if (-not (Test-Path (Join-Path $target "SKILL.md"))) {
            throw "$name has no SKILL.md after install"
        }
        Write-Host "  -> $target"
    }
} finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "Installed to: $SkillsDir"
Write-Host "Next steps:"
Write-Host "  python -m pip install -r `"$SkillsDir\grain-size\requirements.txt`""
Write-Host "  python -m pip install openpyxl"
