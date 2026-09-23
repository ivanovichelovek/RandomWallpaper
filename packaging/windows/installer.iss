; The Windows installer — Inno Setup 6.
;
;   uv run pyinstaller packaging/pyinstaller.spec
;   iscc /DAppVersion=1.1.0 /DOutputName=RandomWallpaper-1.1.0-windows-x64-setup packaging\windows\installer.iss
;
; Per user, no administrator: the app lives under %LOCALAPPDATA%\Programs,
; which is also what lets the in-app updater run the next version's
; installer silently without a UAC prompt in the way.

#ifndef AppVersion
  #error Pass /DAppVersion=x.y.z
#endif
#ifndef OutputName
  #define OutputName "RandomWallpaper-" + AppVersion + "-windows-x64-setup"
#endif

[Setup]
; The AppId ties every version together as one product: an update installs
; over the previous one instead of beside it. Never change it.
AppId={{6E4B7B0C-2F0B-4E7E-9C57-3F1C2B6F7A11}
AppName=Random Wallpaper
AppVersion={#AppVersion}
AppVerName=Random Wallpaper {#AppVersion}
AppPublisher=ivanovichelovek
AppPublisherURL=https://github.com/ivanovichelovek/RandomWallpaper
AppSupportURL=https://github.com/ivanovichelovek/RandomWallpaper/issues
AppUpdatesURL=https://github.com/ivanovichelovek/RandomWallpaper/releases
VersionInfoVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\Random Wallpaper
DefaultGroupName=Random Wallpaper
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist\installer
OutputBaseFilename={#OutputName}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\random-wallpaper.exe
UninstallDisplayName=Random Wallpaper
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; The minute timer may be running random-wallpaper.exe at the moment an
; update lands; Restart Manager closes it (and the window) rather than
; failing on a locked file.
CloseApplications=force
RestartApplications=no
LicenseFile=..\..\LICENSE

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\..\dist\random-wallpaper\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Files a previous version had and this one does not are removed by
; [InstallDelete] below, so an update never leaves a stale DLL behind.

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\Random Wallpaper"; Filename: "{app}\random-wallpaper.exe"
Name: "{group}\Uninstall Random Wallpaper"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Random Wallpaper"; Filename: "{app}\random-wallpaper.exe"; Tasks: desktopicon

[Run]
; Not skipifsilent: the in-app updater runs this installer with /VERYSILENT,
; and this entry is what brings the app back once the new files are in.
Filename: "{app}\random-wallpaper.exe"; Description: "{cm:LaunchProgram,Random Wallpaper}"; Flags: nowait postinstall

[Code]
// The scheduled task starts random-wallpaper.exe every minute. Mid-update —
// after [InstallDelete] has cleared _internal, before the new files are in —
// that start would find half an app, and under /SUPPRESSMSGBOXES a locked
// file aborts the install outright. So the task is paused for the copy and
// resumed after it. Both calls fail harmlessly when there is no task.
procedure SetTimerEnabled(Enabled: Boolean);
var
  Code: Integer;
  Flag: String;
begin
  if Enabled then Flag := '/ENABLE' else Flag := '/DISABLE';
  Exec(ExpandConstant('{sys}\schtasks.exe'), '/Change /TN RandomWallpaperAuto ' + Flag,
       '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  SetTimerEnabled(False);
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    SetTimerEnabled(True);
end;

[UninstallRun]
; The scheduled task would otherwise go on starting an exe that is gone.
Filename: "{app}\random-wallpaper-cli.exe"; Parameters: "--uninstall-timer"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveTimer"
