#ifndef AppVersion
  #error AppVersion must be supplied by the release build
#endif

[Setup]
AppId={{A92F352B-9A7E-4CAB-84F6-839E4F759712}
AppName=LivePaste
AppVersion={#AppVersion}
AppPublisher=Nakshtra Yadav
AppPublisherURL=https://github.com/NakshtraYadav/Live-Paste
DefaultDirName={localappdata}\Programs\LivePaste
DefaultGroupName=LivePaste
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\..\dist
OutputBaseFilename=livepaste-windows-x86_64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableWelcomePage=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableFinishedPage=yes
UninstallDisplayIcon={app}\livepaste.exe
CloseApplications=no
RestartApplications=no
SetupLogging=yes

[Files]
Source: "..\..\dist\livepaste-windows-x86_64.exe"; DestDir: "{app}"; DestName: "livepaste.exe"; Flags: ignoreversion
Source: "launch.vbs"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\LivePaste"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\launch.vbs"""; WorkingDir: "{app}"
Name: "{autodesktop}\LivePaste"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\launch.vbs"""; WorkingDir: "{app}"
Name: "{group}\Stop LivePaste"; Filename: "{app}\livepaste.exe"; Parameters: "stop"; Flags: runminimized
Name: "{group}\Uninstall LivePaste"; Filename: "{uninstallexe}"

[Run]
Filename: "{sys}\wscript.exe"; Parameters: """{app}\launch.vbs"""; Flags: nowait skipifsilent

[UninstallRun]
Filename: "{app}\livepaste.exe"; Parameters: "autostart disable"; Flags: runhidden waituntilterminated; RunOnceId: "DisableStartup"
Filename: "{app}\livepaste.exe"; Parameters: "stop"; Flags: runhidden waituntilterminated; RunOnceId: "StopServer"

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Result := '';
  if FileExists(ExpandConstant('{app}\livepaste.exe')) then
    if not Exec(ExpandConstant('{app}\livepaste.exe'), 'stop', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
      Result := 'LivePaste could not stop safely. Close LivePaste and try setup again. Your saved data has not been removed.';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    if not Exec(ExpandConstant('{app}\livepaste.exe'), 'autostart enable', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
      RaiseException('Could not enable sign-in startup. See %USERPROFILE%\.livepaste\background.log.');
    if not Exec(ExpandConstant('{app}\livepaste.exe'), 'background', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
      RaiseException('LivePaste could not start. See %USERPROFILE%\.livepaste\server.log.');
  end;
end;
