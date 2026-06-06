param(
    [switch]$SkipPrereqDownload,
    [switch]$SkipInnoBuild
)

$ErrorActionPreference = "Stop"

function Resolve-FullPath([string]$Path) {
    return [System.IO.Path]::GetFullPath($Path)
}

function Assert-Under([string]$Path, [string]$Root, [string]$Label) {
    $resolved = Resolve-FullPath $Path
    $base = Resolve-FullPath $Root
    if (-not $resolved.StartsWith($base, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label must stay under $base, got $resolved"
    }
}

function Remove-Tree([string]$Path, [string]$AllowedRoot) {
    if (Test-Path $Path) {
        Assert-Under $Path $AllowedRoot "Remove target"
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

function Copy-Directory([string]$Source, [string]$Destination) {
    if (-not (Test-Path $Source)) {
        throw "Missing required directory: $Source"
    }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    Get-ChildItem -LiteralPath $Source -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $Destination -Recurse -Force
    }
}

function Copy-File([string]$Source, [string]$DestinationDir) {
    if (-not (Test-Path $Source)) {
        throw "Missing required file: $Source"
    }
    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
    Copy-Item -LiteralPath $Source -Destination $DestinationDir -Force
}

function Remove-SourceArchiveNoise([string]$SourceRoot) {
    Get-ChildItem -LiteralPath $SourceRoot -Recurse -Force -Directory |
        Where-Object { $_.Name -eq "__pycache__" -or $_.FullName -like "*\packaging\vendor" } |
        Sort-Object FullName -Descending |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }
    Get-ChildItem -LiteralPath $SourceRoot -Recurse -Force -File |
        Where-Object { $_.Extension -in @(".pyc", ".pyo") } |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }
}

function Test-FileMinBytes([string]$Path, [int64]$MinBytes) {
    if (-not (Test-Path $Path)) {
        return $false
    }
    return ((Get-Item -LiteralPath $Path).Length -ge $MinBytes)
}

function Download-IfMissing([string]$Url, [string]$OutFile, [int64]$MinBytes = 1) {
    if (Test-FileMinBytes $OutFile $MinBytes) {
        return
    }
    Remove-Item -LiteralPath $OutFile -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path (Split-Path $OutFile -Parent) | Out-Null
    Write-Host "Downloading $Url"
    $lastError = $null
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        try {
            Invoke-WebRequest -Uri $Url -OutFile $OutFile
            if (Test-FileMinBytes $OutFile $MinBytes) {
                return
            }
            throw "Downloaded file is smaller than expected: $OutFile"
        } catch {
            $lastError = $_
            Remove-Item -LiteralPath $OutFile -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds (2 * $attempt)
        }
    }
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl) {
        & $curl.Source -L --retry 3 --retry-delay 2 -o $OutFile $Url
        if ($LASTEXITCODE -eq 0 -and (Test-FileMinBytes $OutFile $MinBytes)) {
            return
        }
    }
    throw $lastError
}

function Ensure-MsMpiInstaller([string]$VendorRoot) {
    $target = Join-Path $VendorRoot "msmpisetup.exe"
    $minBytes = 1048576
    if (Test-FileMinBytes $target $minBytes) {
        return $target
    }
    Remove-Item -LiteralPath $target -Force -ErrorAction SilentlyContinue

    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "winget.exe is required to vendor Microsoft MPI installer automatically. Install MS-MPI manually or rerun with a valid packaging\vendor\msmpisetup.exe."
    }

    Write-Host "Downloading Microsoft MPI through winget"
    & $winget.Source download --id Microsoft.msmpi --exact --download-directory $VendorRoot --accept-source-agreements --accept-package-agreements --disable-interactivity
    if ($LASTEXITCODE -ne 0) {
        throw "winget download Microsoft.msmpi failed with exit code $LASTEXITCODE"
    }

    $candidate = Get-ChildItem -LiteralPath $VendorRoot -Recurse -Filter *.exe |
        Where-Object { $_.Length -ge $minBytes -and $_.Name -match "(?i)mpi" } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $candidate) {
        throw "winget did not produce an MS-MPI installer under $VendorRoot"
    }
    Copy-Item -LiteralPath $candidate.FullName -Destination $target -Force
    if (-not (Test-FileMinBytes $target $minBytes)) {
        throw "MS-MPI installer is missing or too small after download: $target"
    }
    return $target
}

function Find-Iscc([string]$ToolsRoot) {
    $candidates = @(
        (Join-Path $ToolsRoot "InnoSetup\ISCC.exe"),
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )
    $pathCandidate = (Get-Command iscc.exe -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($pathCandidate) {
        return $pathCandidate.Source
    }
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) {
            return $candidate
        }
    }
    return $null
}

function Ensure-Inno([string]$ToolsRoot) {
    $iscc = Find-Iscc $ToolsRoot
    if ($iscc) {
        return $iscc
    }
    $installer = Join-Path $ToolsRoot "downloads\innosetup.exe"
    Download-IfMissing "https://jrsoftware.org/download.php/is.exe" $installer
    $target = Join-Path $ToolsRoot "InnoSetup"
    New-Item -ItemType Directory -Force -Path $target | Out-Null
    Write-Host "Installing Inno Setup to $target"
    $args = @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/DIR=$target")
    $process = Start-Process -FilePath $installer -ArgumentList $args -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -ne 0) {
        throw "Inno Setup installer failed with exit code $($process.ExitCode)"
    }
    $iscc = Find-Iscc $ToolsRoot
    if (-not $iscc) {
        throw "ISCC.exe was not found after installing Inno Setup"
    }
    return $iscc
}

function Ensure-BuildPython([string]$ToolsRoot, [string]$Root) {
    $venv = Join-Path $ToolsRoot "rece-build-venv"
    $python = Join-Path $venv "Scripts\python.exe"
    $requirements = Join-Path $Root "requirements.txt"
    $marker = Join-Path $venv ".rece_requirements.sha256"
    if (-not (Test-Path $python)) {
        New-Item -ItemType Directory -Force -Path $ToolsRoot | Out-Null
        Write-Host "Creating packaging Python environment at $venv"
        python -m venv $venv
        if ($LASTEXITCODE -ne 0) {
            throw "Could not create packaging Python environment"
        }
    }
    $hash = (Get-FileHash -Algorithm SHA256 -Path $requirements).Hash
    $installedHash = if (Test-Path $marker) { (Get-Content -LiteralPath $marker -Raw).Trim() } else { "" }
    $hasPyInstaller = Test-Path (Join-Path $venv "Lib\site-packages\PyInstaller\__init__.py")
    if ($installedHash -ne $hash -or -not $hasPyInstaller) {
        $env:PIP_CACHE_DIR = Join-Path $ToolsRoot "pip-cache"
        Write-Host "Installing packaging Python dependencies"
        & $python -m pip install --upgrade pip wheel setuptools | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "pip bootstrap failed"
        }
        & $python -m pip install --upgrade pyinstaller pyinstaller-hooks-contrib | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller installation failed"
        }
        & $python -m pip install -r $requirements | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "Project dependency installation failed"
        }
        Set-Content -LiteralPath $marker -Value $hash -Encoding ASCII
    }
    return $python
}

function Sync-BrandAssets([string]$Python, [string]$Root) {
    $assets = Join-Path $Root "web\assets"
    New-Item -ItemType Directory -Force -Path $assets | Out-Null
    Copy-Item -LiteralPath (Join-Path $Root "art\icon1.png") -Destination (Join-Path $assets "rece-panel-logo.png") -Force
    Copy-Item -LiteralPath (Join-Path $Root "art\icon0.png") -Destination (Join-Path $assets "rece-app-icon.png") -Force
    Copy-Item -LiteralPath (Join-Path $Root "art\logo.png") -Destination (Join-Path $assets "hkust-gz-logo.png") -Force
    $script = @"
from pathlib import Path
from PIL import Image
root = Path(r'''$Root''')
src = root / 'art' / 'icon0.png'
dst = root / 'web' / 'assets' / 'rece-app.ico'
img = Image.open(src).convert('RGBA')
img.save(dst, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
"@
    & $Python -c $script
    if ($LASTEXITCODE -ne 0) {
        throw "Could not generate RECE icon from art\icon0.png"
    }
}

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-FullPath (Join-Path $ScriptRoot "..")
$AAA = Resolve-FullPath (Join-Path $Root "..")
$ToolsRoot = Join-Path $AAA "tools"
$BuildPython = Ensure-BuildPython $ToolsRoot $Root
Sync-BrandAssets $BuildPython $Root
$BuildRoot = Join-Path $Root "build\package"
$Resources = Join-Path $BuildRoot "resources"
$WebStage = Join-Path $Resources "web"
$ThirdPartyStage = Join-Path $Resources "third_party"
$LicensesStage = Join-Path $Resources "licenses"
$SourceStage = Join-Path $BuildRoot "source_stage"
$SourceOut = Join-Path $Resources "source"
$VendorRoot = Join-Path $Root "packaging\vendor"
$DistRoot = Join-Path $Root "dist"
$InstallerOut = Join-Path $DistRoot "installer"
$AppDist = Join-Path $DistRoot "RECE"

Assert-Under $BuildRoot $Root "Build root"
Assert-Under $DistRoot $Root "Dist root"
Remove-Tree $BuildRoot $Root
Remove-Tree $AppDist $Root
New-Item -ItemType Directory -Force -Path $Resources, $WebStage, $ThirdPartyStage, $LicensesStage, $SourceOut, $VendorRoot, $InstallerOut | Out-Null

Write-Host "Staging runtime web resources"
foreach ($file in @("index.html", "favicon.ico", "models.json", "no_waves.txt", "logo_publicex_river.png", "logo_USACE.png", "logo_USC.png", "logo_USC_river.png")) {
    $source = Join-Path $Root "web\$file"
    if (Test-Path $source) {
        Copy-File $source $WebStage
    }
}
foreach ($dir in @("assets", "externals", "js", "shaders", "skybox", "textures")) {
    Copy-Directory (Join-Path $Root "web\$dir") (Join-Path $WebStage $dir)
}

Write-Host "Staging REEF3D and DIVEMesh runtime binaries"
Copy-Directory (Join-Path $Root "third_party\REEF3D\bin") (Join-Path $ThirdPartyStage "REEF3D\bin")

Write-Host "Staging licenses and documentation"
foreach ($file in @("AGENTS.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "SOURCE_MANIFEST.json", "README.md", "README_RECE.md", "requirements.txt", "environment.yml")) {
    Copy-File (Join-Path $Root $file) $LicensesStage
}

Write-Host "Creating corresponding source archive without example data"
Remove-Tree $SourceStage $Root
New-Item -ItemType Directory -Force -Path $SourceStage | Out-Null
foreach ($file in @("AGENTS.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "SOURCE_MANIFEST.json", "README.md", "README_RECE.md", "requirements.txt", "environment.yml")) {
    Copy-File (Join-Path $Root $file) $SourceStage
}
foreach ($dir in @("art", "rece", "tests", "automation", "packaging")) {
    Copy-Directory (Join-Path $Root $dir) (Join-Path $SourceStage $dir)
}
$webSource = Join-Path $SourceStage "web"
New-Item -ItemType Directory -Force -Path $webSource | Out-Null
foreach ($file in @("index.html", "favicon.ico", "models.json", "no_waves.txt", "README.md", "LICENSE")) {
    $source = Join-Path $Root "web\$file"
    if (Test-Path $source) {
        Copy-File $source $webSource
    }
}
foreach ($dir in @("assets", "externals", "js", "shaders", "skybox", "textures")) {
    Copy-Directory (Join-Path $Root "web\$dir") (Join-Path $webSource $dir)
}
Copy-Directory (Join-Path $Root "third_party\REEF3D\src") (Join-Path $SourceStage "third_party\REEF3D\src")
Copy-Directory (Join-Path $Root "third_party\REEF3D\docs") (Join-Path $SourceStage "third_party\REEF3D\docs")
Remove-SourceArchiveNoise $SourceStage
$sourceZip = Join-Path $SourceOut "RECE_corresponding_source.zip"
if (Test-Path $sourceZip) {
    Remove-Item -LiteralPath $sourceZip -Force
}
Compress-Archive -Path (Join-Path $SourceStage "*") -DestinationPath $sourceZip -CompressionLevel Optimal

if (-not $SkipPrereqDownload) {
    Write-Host "Downloading prerequisite installers"
    Download-IfMissing "https://go.microsoft.com/fwlink/p/?LinkId=2124703" (Join-Path $VendorRoot "MicrosoftEdgeWebView2Setup.exe") 1048576
    Ensure-MsMpiInstaller $VendorRoot | Out-Null
}
if (Test-Path $VendorRoot) {
    Copy-Directory $VendorRoot (Join-Path $Resources "vendor")
}

Write-Host "Running PyInstaller"
$env:PYTHONUTF8 = "1"
& $BuildPython -m PyInstaller --noconfirm --clean --distpath $DistRoot --workpath (Join-Path $Root "build\pyinstaller") (Join-Path $Root "packaging\rece_pyinstaller.spec")
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

if (Test-Path (Join-Path $AppDist "_internal\web\examples")) {
    throw "Packaged runtime unexpectedly contains web examples"
}
if (Test-Path (Join-Path $AppDist "_internal\third_party\REEF3D\simulations")) {
    throw "Packaged runtime unexpectedly contains REEF3D simulations"
}

if (-not $SkipInnoBuild) {
    Write-Host "Running Inno Setup"
    $iscc = Ensure-Inno $ToolsRoot
    $env:RECE_INNO_SOURCE_DIR = $AppDist
    $env:RECE_INNO_OUTPUT_DIR = $InstallerOut
    & $iscc (Join-Path $Root "packaging\RECE_Setup.iss")
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup failed with exit code $LASTEXITCODE"
    }
    if (-not (Test-Path (Join-Path $InstallerOut "RECE_Setup.exe"))) {
        throw "RECE_Setup.exe was not produced"
    }
    $installerPath = Join-Path $InstallerOut "RECE_Setup.exe"
    $installerHash = (Get-FileHash -Algorithm SHA256 -Path $installerPath).Hash
    Set-Content -LiteralPath (Join-Path $InstallerOut "RECE_Setup.exe.sha256") -Value "$installerHash *RECE_Setup.exe" -Encoding ASCII
    Write-Host "Installer SHA256: $installerHash"
}

Write-Host "Build complete"
Write-Host "Application: $AppDist"
Write-Host "Installer:   $(Join-Path $InstallerOut 'RECE_Setup.exe')"
