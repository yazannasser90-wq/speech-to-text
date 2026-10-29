; ============================================================
;  Speech To Text - Windows installer script (Inno Setup 6)
;  ينتج مثبّتًا احترافيًا: SpeechToText-Setup.exe
;  التثبيت على مستوى المستخدم (لا يحتاج صلاحيات مسؤول)
; ============================================================

#define MyAppName "Speech To Text"
#define MyAppVersion "1.0"
#define MyAppExeName "SpeechToText.exe"

[Setup]
AppId={{E6C672BB-CEE8-4D67-8F97-2D62D39C5996}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Speech To Text App
DefaultDirName={localappdata}\Programs\SpeechToText
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=installer-output
OutputBaseFilename=SpeechToText-Setup
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\SpeechToText\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
