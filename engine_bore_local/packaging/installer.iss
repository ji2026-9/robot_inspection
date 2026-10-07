[Setup]
AppId={{E4497F79-4F10-477D-AB5F-E7F6E7E93218}
AppName=箱体孔检测系统
AppVersion=1.0.0
DefaultDirName={localappdata}\Programs\EngineBoreInspection
DefaultGroupName=箱体孔检测系统
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=release
OutputBaseFilename=EngineBoreInspection-1.0.0-Setup
Compression=lzma2/fast
LZMANumBlockThreads=4
SolidCompression=no
WizardStyle=modern
UninstallDisplayIcon={app}\箱体孔检测.exe
DisableProgramGroupPage=yes
CloseApplications=no
InfoBeforeFile=payload\使用说明.txt

[Files]
Source: "payload\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "\active_models.json,\data\*,\packaging_test_output\*,__pycache__\*,*.pyc,*.obj,include\*,.inspection_gui.lock"
Source: "payload\active_models.json"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall
Source: "payload\data\*"; DestDir: "{app}\data"; Flags: onlyifdoesntexist uninsneveruninstall recursesubdirs createallsubdirs

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; Flags: checkedonce

[Icons]
Name: "{userdesktop}\箱体孔检测"; Filename: "{app}\箱体孔检测.exe"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{group}\箱体孔检测系统"; Filename: "{app}\箱体孔检测.exe"; WorkingDir: "{app}"
Name: "{group}\使用说明"; Filename: "{app}\使用说明.txt"

[Run]
Filename: "{app}\箱体孔检测.exe"; Description: "打开箱体孔检测系统"; Flags: postinstall nowait skipifsilent

