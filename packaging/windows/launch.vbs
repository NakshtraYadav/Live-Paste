Option Explicit
Dim shell, filesystem, executable
Set shell = CreateObject("WScript.Shell")
Set filesystem = CreateObject("Scripting.FileSystemObject")
executable = filesystem.BuildPath(filesystem.GetParentFolderName(WScript.ScriptFullName), "livepaste.exe")
shell.Run """" & executable & """ background --open", 0, False
