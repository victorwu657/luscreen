; LuScreen 完整版安装脚本（含字幕功能）
#define MyAppName "LuScreen Full"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppPublisher "LuScreen Team"
#define MyAppURL "https://luscreen.com"
#define MyAppExeName "LuScreen.exe"

[Setup]
AppId={{8F9A2B3C-4D5E-6F7A-8B9C-0D1E2F3A4B5D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName=LuScreen
AllowNoIcons=yes
LicenseFile=LICENSE.txt
OutputDir=dist_installer
OutputBaseFilename=LuScreen-Full-Setup-v{#MyAppVersion}
SetupIconFile=assets\icon.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startup"; Description: "开机自动启动"; GroupDescription: "其他选项:"; Flags: unchecked

[Files]
Source: "dist_nuitka\LuScreen.dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion isreadme

[Icons]
Name: "{group}\LuScreen"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 LuScreen"; Filename: "{uninstallexe}"
Name: "{autodesktop}\LuScreen"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "LuScreen"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,LuScreen}"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeUninstall(): Boolean;
var
  Response: Integer;
begin
  Result := True;
  Response := MsgBox('是否同时删除录制文件、配置和模型？', mbConfirmation, MB_YESNOCANCEL);
  if Response = IDCANCEL then
    Result := False
  else if Response = IDYES then
  begin
    DelTree(ExpandConstant('{userappdata}\LuScreen'), True, True, True);
    DelTree(ExpandConstant('{userdocs}\LuScreen'), True, True, True);
  end;
end;
