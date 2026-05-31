; UACRAgent Inno Setup script
; Build: pyinstaller UACRAgent_win.spec, then iscc UACRAgent_installer.iss

#define AppName      "UACRAgent"
#define AppVersion   "0.3.0"
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
OutputBaseFilename=UACRAgent-{#AppVersion}-windows-setup
SetupIconFile=assets\UACRAgent.ico
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