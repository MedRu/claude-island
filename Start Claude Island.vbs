' Claude Island - a desktop widget for watching your Claude Code sessions
' Copyright (c) 2026 Mohamed HAMANA (github.com/MedRu). MIT License, see LICENSE.
' Starts Claude Island with no console window. Double-click it to start the widget alone.
' Claude Code hooks call it with --hook, so the widget knows a chat started it.
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
args = ""
For Each a In WScript.Arguments
    args = args & " " & a
Next
' Window style 1, not 0: pythonw has no console anyway, and Windows would apply a hidden style
' to the first normal window the program shows, which is the settings window.
CreateObject("WScript.Shell").Run "pythonw """ & here & "\island.py""" & args, 1
