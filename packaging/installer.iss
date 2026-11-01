; Inno Setup 6 script — per-user install, no admin rights required.
#define AppName "LectureScribe"
#define AppVer GetEnv("LS_VERSION")
#if AppVer == ""
  #define AppVer "0.1.0"
#endif

[Setup]
AppId={{6F0B7C3E-2B4E-4E7B-9C1D-5A3B1E8D2F47}
AppName={#AppName}
AppVersion={#AppVer}
AppPublisher=LectureScribe
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\installer
OutputBaseFilename=LectureScribe-Setup-{#AppVer}
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\LectureScribe.exe
InfoBeforeFile=..\THIRD_PARTY_NOTICES.md
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\LectureScribe\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\LectureScribe.exe"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\LectureScribe.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\LectureScribe.exe"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; temp audio only; transcripts cache, settings and downloaded models in %LOCALAPPDATA%\LectureScribe are kept
Type: filesandordirs; Name: "{localappdata}\LectureScribe\tmp"
