; UACRAgent Inno Setup script
;
; Build sequence:
;   pyinstaller UACRAgent_win.spec
;   iscc /DAppVersion=X.Y.Z UACRAgent_installer.iss
;
; The version MUST be passed on the command line so the output filename
; matches the pattern the auto-updater looks for:
;   UACRAgent-vX.Y.Z-windows-x64-setup.exe
;
; In CI (e.g. GitHub Actions) extract the version from pyproject.toml:
;   VERSION=$(python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")
;   iscc /DAppVersion=$VERSION UACRAgent_installer.iss

#ifndef AppVersion
  ; Fallback: let the build fail loudly rather than silently use a stale version.
  #error "AppVersion must be defined via the command line: iscc /DAppVersion=X.Y.Z"
#endif

#define AppName      "UACRAgent"
#define AppPublisher "Lizhuo Xu"
#define AppURL       "https://joe20252030.github.io/University_Academic_Course_Review_Agent/"
#define AppExeName   "UACRAgent.exe"
#define SourceDir    "dist\UACRAgent"

[Setup]
AppId={{8F3A2B1C-4D5E-4F6A-9B0C-1D2E3F4A5B6C}}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
AllowNoIcons=yes
LicenseFile=LICENSE
OutputDir=installer_output
; Filename must match the auto-updater asset pattern: UACRAgent-v{version}-windows-x64-setup.exe
OutputBaseFilename=UACRAgent-v{#AppVersion}-windows-x64-setup
SetupIconFile=assets\logo.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequiredOverridesAllowed=dialog
; Minimum Windows version: Windows 10
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Copy all PyInstaller output into the install directory
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Start Menu shortcut
Name: "{group}\{#AppName}";          Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
; Desktop shortcut (optional, only if user ticked the task above)
Name: "{autodesktop}\{#AppName}";    Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
; Offer to launch the app after installation completes
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; \
  Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Clean up any files the app writes into the install directory on uninstall
Type: filesandordirs; Name: "{app}"