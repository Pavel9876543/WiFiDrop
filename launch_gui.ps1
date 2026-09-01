param()

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Show-Error([string]$Message) {
    try {
        Add-Type -AssemblyName PresentationFramework -ErrorAction Stop
        [System.Windows.MessageBox]::Show(
            $Message,
            'WiFiDrop',
            [System.Windows.MessageBoxButton]::OK,
            [System.Windows.MessageBoxImage]::Error
        ) | Out-Null
    }
    catch {
        $shell = New-Object -ComObject WScript.Shell
        $shell.Popup($Message, 0, 'WiFiDrop', 16) | Out-Null
    }
}

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Administrator)) {
    $args = @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-WindowStyle', 'Hidden',
        '-File', ('"{0}"' -f $PSCommandPath)
    )
    try {
        Start-Process -FilePath 'powershell.exe' -Verb RunAs -WindowStyle Hidden -ArgumentList $args | Out-Null
    }
    catch {
        Show-Error 'Administrator privileges are required to run WiFiDrop.'
    }
    exit
}

try {
    $python = $null
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $python = $pythonCommand.Source
    }

    if (-not $python) {
        $pyCommand = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($pyCommand) {
            $python = (& $pyCommand.Source -3 -c 'import sys; print(sys.executable)' 2>$null | Select-Object -First 1).Trim()
        }
    }

    if (-not $python -or -not (Test-Path $python)) {
        Show-Error 'Python 3.10 or newer was not found. Install Python and enable Add Python to PATH.'
        exit 1
    }

    $versionCheck = Start-Process -FilePath $python -ArgumentList @(
        '-c', 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)'
    ) -WorkingDirectory $Root -WindowStyle Hidden -Wait -PassThru
    if ($versionCheck.ExitCode -ne 0) {
        Show-Error 'WiFiDrop requires Python 3.10 or newer.'
        exit 1
    }

    $dependencyCheck = Start-Process -FilePath $python -ArgumentList @(
        '-c', 'import PyQt6, fastapi, uvicorn'
    ) -WorkingDirectory $Root -WindowStyle Hidden -Wait -PassThru

    if ($dependencyCheck.ExitCode -ne 0) {
        $install = Start-Process -FilePath $python -ArgumentList @(
            '-m', 'pip', 'install', '-r', (Join-Path $Root 'requirements.txt')
        ) -WorkingDirectory $Root -WindowStyle Hidden -Wait -PassThru
        if ($install.ExitCode -ne 0) {
            Show-Error 'Failed to install WiFiDrop dependencies. Check the Internet connection and Python installation.'
            exit 1
        }
    }

    $pythonDir = Split-Path -Parent $python
    $pythonw = Join-Path $pythonDir 'pythonw.exe'
    if (-not (Test-Path $pythonw)) {
        $pythonw = $python
    }

    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'

    Start-Process -FilePath $pythonw -ArgumentList @('-X', 'utf8', '-m', 'app.gui') -WorkingDirectory $Root -WindowStyle Hidden | Out-Null
}
catch {
    Show-Error ("WiFiDrop failed to start:`n" + $_.Exception.Message)
    exit 1
}
