; The wizard's Windows zip as a per-user installer (ADR-0061).
; Built by packaging/windows_installer.py, which passes:
;   /DAppVersion=<iemod-fetch's version>  /DSourceDir=<the zip's folder>
;   /DOutputDir=<dist>  /DOutputName=<file name, no .exe>
;
; Per user, no administrator: PrivilegesRequired=lowest puts {autopf} in
; %LOCALAPPDATA%\Programs. The uninstaller removes what it installed and
; nothing else: no [UninstallDelete] - the projects, the community-data cache
; (%LOCALAPPDATA%\iemod-fetch\data) and anything the player made stay.
; An upgrade empties _internal first ([InstallDelete]): it is PyInstaller's,
; all of it, and a library the new version no longer carries must not stay.
; A downgrade is not refused: an older installer replaces a newer version.

#ifndef AppVersion
  #error AppVersion is passed by packaging/windows_installer.py
#endif

[Setup]
AppId={{483B2769-37EB-4CC9-B7A8-410A2C01BCD1}
AppName=iemod-fetch
AppVersion={#AppVersion}
AppVerName=iemod-fetch {#AppVersion}
AppPublisher=iemod-fetch contributors
AppPublisherURL=https://github.com/gsamuele78/iemod-fetch
AppSupportURL=https://github.com/gsamuele78/iemod-fetch/issues
PrivilegesRequired=lowest
DefaultDirName={autopf}\iemod-fetch-gui
DisableProgramGroupPage=yes
DefaultGroupName=iemod-fetch
LicenseFile={#SourceDir}\LICENSE
OutputDir={#OutputDir}
OutputBaseFilename={#OutputName}
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\iemod-fetch-gui.exe
; no version in the name: winget matches the entry by it (ADR-0062); the
; version is DisplayVersion, beside it
UninstallDisplayName=iemod-fetch
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Files]
; the zip's folder, plus Inno Setup's licence and NOTICE-installer.txt: the
; program, Qt as separate DLLs (LGPL-3.0), mod_installer, LICENSE, NOTICE-*.txt
; and licenses\
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\iemod-fetch"; Filename: "{app}\iemod-fetch-gui.exe"
Name: "{autodesktop}\iemod-fetch"; Filename: "{app}\iemod-fetch-gui.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\iemod-fetch-gui.exe"; Description: "{cm:LaunchProgram,iemod-fetch}"; Flags: nowait postinstall skipifsilent
