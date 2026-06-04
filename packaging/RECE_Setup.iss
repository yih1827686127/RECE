#define SourceDir GetEnv("RECE_INNO_SOURCE_DIR")
#define OutputDir GetEnv("RECE_INNO_OUTPUT_DIR")

[Setup]
AppId={{6F01723F-0C62-4E0A-BAC7-CA0DB7E14207}
AppName=RECE
AppVersion=0.1.0
AppPublisher=HKUST-GZ / MHRF
DefaultDirName={autopf}\RECE
DefaultGroupName=RECE
DisableProgramGroupPage=yes
OutputDir={#OutputDir}
OutputBaseFilename=RECE_Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
LicenseFile={#SourceDir}\_internal\licenses\LICENSE
SetupIconFile={#SourceDir}\_internal\web\assets\rece-app.ico
UninstallDisplayIcon={app}\RECE.exe
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: checkedonce

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\RECE"; Filename: "{app}\RECE.exe"
Name: "{group}\Uninstall RECE"; Filename: "{uninstallexe}"
Name: "{autodesktop}\RECE"; Filename: "{app}\RECE.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\_internal\vendor\MicrosoftEdgeWebView2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "Installing Microsoft Edge WebView2 Runtime..."; Flags: waituntilterminated; Check: ShouldInstallWebView2
Filename: "{app}\_internal\vendor\msmpisetup.exe"; Parameters: "-unattend"; StatusMsg: "Installing Microsoft MPI Runtime..."; Flags: waituntilterminated; Check: ShouldInstallMpi
Filename: "{app}\RECE.exe"; Description: "Launch RECE"; Flags: nowait postinstall skipifsilent

[Code]
function WebView2RegExists(Root: Integer; Key: String): Boolean;
var
  Version: String;
begin
  Result := RegQueryStringValue(Root, Key, 'pv', Version) and (Length(Version) > 0);
end;

function IsWebView2Installed(): Boolean;
begin
  Result :=
    WebView2RegExists(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}') or
    WebView2RegExists(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}') or
    WebView2RegExists(HKCU, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}');
end;

function IsMpiInstalled(): Boolean;
begin
  Result :=
    FileExists(ExpandConstant('{pf}\Microsoft MPI\Bin\mpiexec.exe')) or
    FileExists(ExpandConstant('{pf64}\Microsoft MPI\Bin\mpiexec.exe'));
end;

function ShouldInstallWebView2(): Boolean;
begin
  Result :=
    (not IsWebView2Installed()) and
    FileExists(ExpandConstant('{app}\_internal\vendor\MicrosoftEdgeWebView2Setup.exe'));
end;

function ShouldInstallMpi(): Boolean;
begin
  Result :=
    (not IsMpiInstalled()) and
    FileExists(ExpandConstant('{app}\_internal\vendor\msmpisetup.exe'));
end;
