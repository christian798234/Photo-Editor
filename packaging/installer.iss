; Inno Setup script for Bird Photo Editor.
; Build: iscc /DAppVersion=0.3.0 packaging\installer.iss  (after PyInstaller)
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F1B9C52-4D7E-4C0B-9E2A-7A3B5D1C8E44}
AppName=Bird Photo Editor
AppVersion={#AppVersion}
AppPublisher=Bird Photo Editor
DefaultDirName={autopf}\Bird Photo Editor
DefaultGroupName=Bird Photo Editor
DisableProgramGroupPage=yes
; Per-user install by default (no administrator rights); an admin may
; choose "install for all users" in the dialog.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
WizardStyle=modern
OutputDir=..\dist\installer
OutputBaseFilename=BirdPhotoEditor-Setup-{#AppVersion}
SetupIconFile=build\icon.ico
UninstallDisplayIcon={app}\BirdPhotoEditor.exe
UninstallDisplayName=Bird Photo Editor
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
InfoBeforeFile=..\packaging\THIRD-PARTY-NOTICES.txt

[Types]
Name: "full"; Description: "Full installation (recommended)"
Name: "basic"; Description: "Without bird detection (smaller)"
Name: "custom"; Description: "Custom"; Flags: iscustom

[Components]
Name: "main"; Description: "Bird Photo Editor"; Types: full basic custom; Flags: fixed
Name: "birds"; Description: "Bird detection models (about 80 MB, runs only on this PC; switched on inside the app)"; Types: full

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\BirdPhotoEditor\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Components: main
Source: "..\backend\models\*.onnx"; DestDir: "{app}\models"; Flags: ignoreversion; Components: birds
Source: "..\backend\models\README.md"; DestDir: "{app}\models"; Flags: ignoreversion; Components: birds
Source: "..\backend\models\LICENSE-*.txt"; DestDir: "{app}\models"; Flags: ignoreversion; Components: birds
Source: "..\packaging\THIRD-PARTY-NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion

[InstallDelete]
; Remove models from an earlier install if the component is now deselected.
Type: filesandordirs; Name: "{app}\models"; Components: not birds

[Icons]
Name: "{group}\Bird Photo Editor"; Filename: "{app}\BirdPhotoEditor.exe"
Name: "{group}\Uninstall Bird Photo Editor"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Bird Photo Editor"; Filename: "{app}\BirdPhotoEditor.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\BirdPhotoEditor.exe"; Description: "Start Bird Photo Editor now"; Flags: nowait postinstall skipifsilent

[Code]
{ ---------------------------------------------------------------------------
  Running the installer when Bird Photo Editor is already installed offers a
  choice: update/reinstall, or uninstall.
  --------------------------------------------------------------------------- }
function GetUninstallString(): String;
var
  Key, Value: String;
begin
  Key := ExpandConstant('Software\Microsoft\Windows\CurrentVersion\Uninstall\{#SetupSetting("AppId")}_is1');
  Value := '';
  if not RegQueryStringValue(HKCU, Key, 'UninstallString', Value) then
    RegQueryStringValue(HKLM, Key, 'UninstallString', Value);
  Result := Value;
end;

function InitializeSetup(): Boolean;
var
  Uninstaller: String;
  Choice, Code: Integer;
begin
  Result := True;
  Uninstaller := GetUninstallString();
  if (Uninstaller = '') or WizardSilent then
    Exit;
  Choice := TaskDialogMsgBox('Bird Photo Editor is already installed',
    'What would you like to do?' + #13#10 + #13#10 +
    'Update / reinstall keeps your photos, edits and settings.' + #13#10 +
    'Uninstall removes the program (you will be asked whether to also delete saved edits).' + #13#10 +
    'Your original photos and exported files are never touched.',
    mbConfirmation, MB_YESNOCANCEL, ['Update / reinstall', 'Uninstall'], 0);
  if Choice = IDYES then
    Exit;
  Result := False;
  if Choice = IDNO then
    Exec(RemoveQuotes(Uninstaller), '', '', SW_SHOW, ewWaitUntilTerminated, Code);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\BirdPhotoEditor');
    if DirExists(DataDir) and not UninstallSilent then
      if MsgBox('Also delete your saved edits, previews and copies of photos you dragged into the app?' + #13#10 + #13#10 +
                'Your original photos and exported files are NOT affected either way.' + #13#10 +
                '(' + DataDir + ')', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
