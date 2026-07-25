Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.Run Chr(34) & scriptDir & "\run.bat" & Chr(34), 0
Set WshShell = Nothing
