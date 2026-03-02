[Setup]
; NOTE: The value of AppId uniquely identifies this application.
; Do not use the same AppId value in installers for other applications.
; (To generate a new GUID, click Tools | Generate GUID inside Inno Setup)
AppId={{A1B2C3D4-E5F6-7890-1234-567890ABCDEF}
AppName=BaseWeight
AppVersion=1.0
AppPublisher=BaseWeight Co.
AppExeName=BaseWeight.exe

; Install to Program Files by default
DefaultDirName={autopf}\BaseWeight
DefaultGroupName=BaseWeight

; Output the installer exe to the current folder
OutputDir=.
OutputBaseFilename=BaseWeight_Installer

; Use the icon we generated
UninstallDisplayIcon={app}\BaseWeight.exe

; Compression settings for a smaller installer
Compression=lzma2
SolidCompression=yes

; Require admin rights to install (standard for Program Files)
PrivilegesRequired=admin

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Dirs]
; CRITICAL: Grant users write permission to the install folder.
; This allows app.py to create 'gear.db' and 'uploads/' next to the exe.
Name: "{app}"; Permissions: users-modify

[Files]
; Copy the PyInstaller build (renaming HikerApp.exe to BaseWeight.exe)
Source: "dist\BaseWeight.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\BaseWeight"; Filename: "{app}\BaseWeight.exe"
Name: "{autodesktop}\BaseWeight"; Filename: "{app}\BaseWeight.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\BaseWeight.exe"; Description: "{cm:LaunchProgram,BaseWeight}"; Flags: nowait postinstall skipifdoesntexist