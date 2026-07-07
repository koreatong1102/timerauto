#ifndef TimerAutoVersion
  #define TimerAutoVersion "1.0.0"
#endif

[Setup]
AppName=TimerAuto
AppVersion={#TimerAutoVersion}
DefaultDirName={localappdata}\TimerAuto
DefaultGroupName=TimerAuto
OutputDir=.
OutputBaseFilename=TimerAuto_Setup_{#TimerAutoVersion}
Compression=lzma
SolidCompression=yes
DisableProgramGroupPage=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "..\\dist\\timerauto\\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "logs\\*"

[Icons]
Name: "{group}\\TimerAuto"; Filename: "{app}\\timerauto.exe"
Name: "{commondesktop}\\TimerAuto"; Filename: "{app}\\timerauto.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop icon"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\\timerauto.exe"; Description: "Launch TimerAuto"; Flags: nowait postinstall skipifsilent
