; LuScreen Inno Setup 安装脚本
; 版本由构建脚本从 src/version.py 注入

#define MyAppName "LuScreen"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppPublisher "LuScreen Team"
#define MyAppURL "https://luscreen.com"
#define MyAppExeName "LuScreen.exe"
#ifndef LUSCREEN_PACKAGE_FLAVOR
  #define LUSCREEN_PACKAGE_FLAVOR "release"
#endif
#if LUSCREEN_PACKAGE_FLAVOR == "debug"
  #define MyAppDisplayName "LuScreen Debug"
  #define MyAppInstallDirName "LuScreen-Debug"
  #define MyOutputBaseFilename "LuScreen-Debug-Setup-v" + MyAppVersion
#else
  #define MyAppDisplayName MyAppName
  #define MyAppInstallDirName MyAppName
  #define MyOutputBaseFilename "LuScreen-Setup-v" + MyAppVersion
#endif

[Setup]
AppId={{8F9A2B3C-4D5E-6F7A-8B9C-0D1E2F3A4B5C}
AppName={#MyAppDisplayName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppInstallDirName}
DefaultGroupName={#MyAppDisplayName}
AllowNoIcons=yes
LicenseFile=LICENSE.txt
OutputDir=dist_installer
OutputBaseFilename={#MyOutputBaseFilename}
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

[Dirs]
Name: "{app}\logs"

[Files]
; 主程序 (从 Nuitka 编译输出目录)
Source: "dist_nuitka\LuScreen.dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; 配置文件模板
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion isreadme

[Icons]
Name: "{group}\{#MyAppDisplayName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppDisplayName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppDisplayName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userappdata}\Microsoft\Internet Explorer\Quick Launch\{#MyAppDisplayName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: quicklaunchicon

[Registry]
; 开机自启动
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppDisplayName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

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
