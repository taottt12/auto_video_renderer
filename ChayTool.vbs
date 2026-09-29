' ========================================================
' File khoi chay Auto Video Renderer 100% An cua so CMD
' ========================================================
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WshShell.Run "ChayTool.bat", 0, False
Set WshShell = Nothing
