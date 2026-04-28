; TextSpeak Pro - Inno Setup installer script
; (C) 2026 JojoLapin Inc. All rights reserved.
;
; Requires:  Inno Setup 6+   https://jrsoftware.org/isdl.php
; Builds the portable .exe into an installer with Start Menu shortcut,
; optional desktop icon, and a proper uninstaller.

#define MyAppName        "TextSpeak Pro"
#define MyAppVersion     "1.0.0"
#define MyAppPublisher   "JojoLapin Inc."
#define MyAppURL         "https://github.com/"
#define MyAppExeName     "TextSpeakPro.exe"
#define MyAppTM          "TextSpeak Pro(TM)"
#define MyAppCopyright   "(C) 2026 JojoLapin Inc. All rights reserved."

[Setup]
AppId={{C3F46CCD-5B7E-4F2D-93F1-6E9B7F5DE2CA}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
VersionInfoVersion={#MyAppVersion}.0
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppCopyright={#MyAppCopyright}
DefaultDirName={autopf}\TextSpeak Pro
DefaultGroupName=TextSpeak Pro
DisableProgramGroupPage=yes
DisableDirPage=no
OutputBaseFilename=TextSpeakPro-Setup-{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequiredOverridesAllowed=commandline dialog
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=..\resources\icon.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "french";  MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "quicklaunchicon"; Description: "{cm:CreateQuickLaunchIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked; OnlyBelowVersion: 6.1

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
