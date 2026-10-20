; SystemWatch installer - compiled by build.py with Inno Setup 6.
;
; Per-user install: no administrator rights, nothing outside the user's own
; profile. Installs to %LOCALAPPDATA%\Programs\SystemWatch.

#define AppName "SystemWatch"
; build.py passes /DAppVersion=<version.py>; this is only the fallback.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppExe "SystemWatch.exe"

[Setup]
AppId={{6E3B2C1A-5F4D-4B7E-9C2A-8D1F0E7A3B95}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Al-Baraa Ibrahim Melhem
AppPublisherURL=https://github.com/Baraa-Melhem/SystemWatch
AppSupportURL=https://github.com/Baraa-Melhem/SystemWatch/issues
AppUpdatesURL=https://github.com/Baraa-Melhem/SystemWatch/releases
AppCopyright=Copyright (C) 2026 Al-Baraa Ibrahim Melhem. GNU GPL v3 or later.
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} installer
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\release
OutputBaseFilename=SystemWatch-Setup-{#AppVersion}
SetupIconFile=systemwatch.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=force

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "autostart"; Description: "Start SystemWatch in the &tray when I sign in to Windows"; GroupDescription: "Startup:"

[Files]
Source: "dist\SystemWatch\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; The GPL travels with the binary, as it requires, along with the notices
; for the bundled Python, PyQt5, Qt, pywin32 and psutil.
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion
Source: "..\THIRD-PARTY-NOTICES.md"; DestDir: "{app}"; DestName: "THIRD-PARTY-NOTICES.txt"; Flags: ignoreversion

[InstallDelete]
; An upgrade replaces the whole bundle, so files a newer build no longer
; ships cannot linger and be loaded by mistake.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; Comment: "Read-only Windows event monitor"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
; Same name the in-app "start with Windows" setting uses, so that toggle
; recognises it and can turn it off again.
Name: "{userstartup}\SystemWatch"; Filename: "{app}\{#AppExe}"; Parameters: "--tray"; Tasks: autostart

[Run]
Filename: "{app}\{#AppExe}"; Description: "Open SystemWatch now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Login shortcuts the app itself may have created from its Settings dialog.
Type: files; Name: "{userstartup}\SystemWatch.lnk"
Type: files; Name: "{userstartup}\SystemWatch Recorder.lnk"

[Code]
// Ask the recorder to stop cleanly (it finishes any write in progress),
// then force-close whatever is left. The recorder has no window, so Restart
// Manager cannot ask it to close; taskkill is the backstop, and it is scoped
// to this install's own exe path so nothing else of that name is touched.
procedure StopSystemWatch(const Exe: String);
var
  Code: Integer;
  Quoted: String;
begin
  if not FileExists(Exe) then
    Exit;
  Exec(Exe, '--recorder --stop', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Sleep(800);
  // PowerShell single-quoted string: an apostrophe in the path (a user
  // folder like C:\Users\O'Brien) is escaped by doubling it.
  Quoted := Exe;
  StringChangeEx(Quoted, '''', '''''', True);
  Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -NonInteractive -Command "Get-Process SystemWatch -ErrorAction SilentlyContinue | ' +
    'Where-Object { $_.Path -eq ''' + Quoted + ''' } | Stop-Process -Force"',
    '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopSystemWatch(ExpandConstant('{app}\{#AppExe}'));
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir, BackupDir: String;
begin
  if CurUninstallStep = usUninstall then
    StopSystemWatch(ExpandConstant('{app}\{#AppExe}'));

  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\{#AppName}');
    BackupDir := ExpandConstant('{userappdata}\{#AppName}');
    // The records are the user's, so they are kept unless they say
    // otherwise. A silent uninstall always keeps them.
    if (DirExists(DataDir) or DirExists(BackupDir)) and not UninstallSilent then
      if MsgBox('Also delete your SystemWatch settings and recorded history?' + #13#10#13#10 +
                'Choose No to keep them, for example if you plan to reinstall.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      begin
        DelTree(DataDir, True, True, True);
        DelTree(BackupDir, True, True, True);
      end;
  end;
end;
