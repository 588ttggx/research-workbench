; Bootstrap installer. Runtime ZIPs are verified by Install.ps1 before use.
; ISCC /DReleaseDir=... /DSetupOutputDir=... /DAppVersion=... setup.iss
#ifndef ReleaseDir
  #error ReleaseDir must contain manifest.json, Install.ps1 and Install.cmd.
#endif
#ifndef SetupOutputDir
  #define SetupOutputDir ReleaseDir
#endif
#ifndef AppVersion
  #define AppVersion "0.1.0-preview.1"
#endif

[Setup]
AppId={{D997AE80-EB36-4777-B908-8623CE84D821}
AppName=Research Workbench
AppVersion={#AppVersion}
VersionInfoVersion=0.1.0.0
AppPublisher=Research Workbench Contributors
AppPublisherURL=https://github.com/588ttggx/research-workbench
DefaultDirName={localappdata}\ResearchWorkbench
UsePreviousAppDir=no
DisableProgramGroupPage=yes
DisableReadyPage=no
DirExistsWarning=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
Uninstallable=no
CreateUninstallRegKey=no
CloseApplications=no
RestartApplications=no
SetupLogging=yes
OutputDir={#SetupOutputDir}
OutputBaseFilename=ResearchWorkbench-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
#ifdef LicenseFile
LicenseFile={#LicenseFile}
#endif

[Files]
Source: "{#ReleaseDir}\Install.ps1"; Flags: dontcopy noencryption
Source: "{#ReleaseDir}\Install.cmd"; Flags: dontcopy noencryption
Source: "{#ReleaseDir}\manifest.json"; Flags: dontcopy noencryption

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Types]
Name: standard; Description: "Base workspace"
Name: custom; Description: "Choose optional tools"; Flags: iscustom

[Components]
Name: core; Description: "Base workspace (Python, Node.js, Open Notebook)"; Types: standard custom; Flags: fixed
Name: local_retrieval; Description: "Local document retrieval (Ollama and Qwen3 Embedding 4B)"
Name: r; Description: "R statistical runtime"
Name: graphviz; Description: "Graphviz diagrams"
Name: pwsh; Description: "PowerShell 7"

[Run]
Filename: "{app}\打开科研区.cmd"; Description: "Open Research Workbench"; Flags: postinstall nowait skipifsilent runhidden

[Code]
var
  CompletedTarget: String;
  LastInstallerOutput: String;

procedure LogInstallerOutput(const S: String; const Error, FirstLine: Boolean);
begin
  Log(S);
  if Trim(S) <> '' then
    LastInstallerOutput := Copy(S, 1, 1000);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Parameters: String;
  ExitCode: Integer;
  PowerShell: String;
  SelectedGroups: String;
begin
  Result := '';
  if CompletedTarget = WizardDirValue then
    Exit;
  try
    ExtractTemporaryFile('Install.ps1');
    ExtractTemporaryFile('Install.cmd');
    ExtractTemporaryFile('manifest.json');
    PowerShell := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
    Parameters := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File ' +
      AddQuotes(ExpandConstant('{tmp}\Install.ps1')) +
      ' -ManifestPath ' + AddQuotes(ExpandConstant('{tmp}\manifest.json')) +
      ' -AssetDirectory ' + AddQuotes(ExpandConstant('{src}')) +
      ' -InstallDir ' + AddQuotes(WizardDirValue) + ' -NoLaunch';
    if not WizardIsTaskSelected('desktopicon') then
      Parameters := Parameters + ' -NoShortcut';
    SelectedGroups := '';
    if WizardIsComponentSelected('local_retrieval') then
      SelectedGroups := 'qwen4b';
    if WizardIsComponentSelected('r') then
      SelectedGroups := SelectedGroups + ',r';
    if WizardIsComponentSelected('graphviz') then
      SelectedGroups := SelectedGroups + ',graphviz';
    if WizardIsComponentSelected('pwsh') then
      SelectedGroups := SelectedGroups + ',powershell';
    if SelectedGroups <> '' then
      Parameters := Parameters + ' -Components ' + AddQuotes(SelectedGroups);
    LastInstallerOutput := '';
    if not ExecAndLogOutput(PowerShell, Parameters, ExpandConstant('{tmp}'),
      SW_HIDE, ewWaitUntilTerminated, ExitCode, @LogInstallerOutput) then
      Result := 'Unable to start Windows PowerShell: ' + SysErrorMessage(ExitCode)
    else if ExitCode <> 0 then
      Result := 'Installation did not finish. ' + LastInstallerOutput + #13#10 +
        'Existing workspace files were preserved. See the setup log for details.'
    else
      CompletedTarget := WizardDirValue;
  except
    Result := GetExceptionMessage;
  end;
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo,
  MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
begin
  Result := MemoDirInfo + NewLine + NewLine +
    'The installer checks for runtime ZIPs beside this Setup file, then downloads missing components from GitHub Releases.' +
    NewLine + 'Python and Node.js do not need to be installed beforehand.' +
    NewLine + 'Choose a new empty directory. Existing workspaces are never overwritten.' +
    NewLine + NewLine + MemoComponentsInfo + NewLine + MemoTasksInfo;
end;
