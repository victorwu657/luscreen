; LuScreen Inno Setup 安装脚本
; 版本: 0.046.9

#define MyAppName "LuScreen"
#define MyAppVersion "0.046.9"
#define MyAppPublisher "LuScreen Team"
#define MyAppURL "https://luscreen.com"
#define MyAppExeName "LuScreen.exe"

[Setup]
AppId={{8F9A2B3C-4D5E-6F7A-8B9C-0D1E2F3A4B5C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=LICENSE.txt
OutputDir=dist_installer
OutputBaseFilename=LuScreen-Setup-v{#MyAppVersion}
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
Name: "quicklaunchicon"; Description: "创建快速启动栏图标"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startup"; Description: "开机自动启动"; GroupDescription: "其他选项:"; Flags: unchecked

[Files]
; 主程序 (从 Nuitka 编译输出目录)
Source: "dist_nuitka\LuScreen.dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; 配置文件模板
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion isreadme

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: quicklaunchicon

[Registry]
; 开机自启动
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{userappdata}\LuScreen\logs"
Type: filesandordirs; Name: "{userappdata}\LuScreen\.download_cache"

[Code]
var
  DataDirPage: TInputDirWizardPage;
  KeepUserDataCheck: TNewCheckBox;

procedure InitializeWizard;
begin
  // 创建自定义页面询问是否保留用户数据
end;

function InitializeUninstall(): Boolean;
var
  Response: Integer;
begin
  Result := True;
  Response := MsgBox('是否同时删除录制文件、配置和下载的模型？' + #13#10 +
                     '选择"是"将删除所有用户数据' + #13#10 +
                     '选择"否"将保留用户数据',
                     mbConfirmation, MB_YESNOCANCEL);

  if Response = IDCANCEL then
    Result := False
  else if Response = IDYES then
  begin
    // 删除用户数据
    DelTree(ExpandConstant('{userappdata}\LuScreen'), True, True, True);
    DelTree(ExpandConstant('{userdocs}\LuScreen'), True, True, True);
  end;
end;
