; 格式转换器 安装包脚本（Inno Setup 6）——由 build.ps1 调用
#define AppName "格式转换器"
#define AppVersion "1.4.1"
#define AppPublisher "RonganBai"
#define AppExe "FormatConverter.exe"
#ifndef DistDir
  #define DistDir "..\dist\FormatConverter"
#endif

[Setup]
AppId={{B3C1D7E2-5A4F-4E8B-9C6D-2F1A7E3B9D50}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\FormatConverter
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=Output
OutputBaseFilename=FormatConverter-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
VersionInfoVersion={#AppVersion}
VersionInfoProductName=Format Converter

[Languages]
Name: "default"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
default.TaskDesktop=创建桌面快捷方式 / Create a desktop shortcut
default.GroupExtra=附加选项 / Additional options:
default.LaunchApp=立即运行 格式转换器 / Launch Format Converter

[Tasks]
Name: "desktopicon"; Description: "{cm:TaskDesktop}"; GroupDescription: "{cm:GroupExtra}"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchApp}"; Flags: nowait postinstall skipifsilent
