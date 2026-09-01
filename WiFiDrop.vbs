Option Explicit

Dim mode, shellApp, shell, fso, root, batPath, args, q, message
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
q = Chr(34)

If WScript.Arguments.Count = 0 Then
    shell.Run q & root & "\run_gui.bat" & q, 0, False
    WScript.Quit 0
End If

mode = LCase(WScript.Arguments(0))
If mode = "error" Then
    If WScript.Arguments.Count >= 2 Then
        message = WScript.Arguments(1)
    Else
        message = "WiFiDrop failed to start."
    End If
    shell.Popup message, 0, "WiFiDrop", 16
    WScript.Quit 0
End If

If mode = "elevate" Then
    If WScript.Arguments.Count >= 2 Then
        batPath = WScript.Arguments(1)
    Else
        shell.Popup "Launcher path is missing.", 0, "WiFiDrop", 16
        WScript.Quit 1
    End If
    Set shellApp = CreateObject("Shell.Application")
    args = "/d /s /c " & q & q & batPath & q & " --elevated" & q
    On Error Resume Next
    shellApp.ShellExecute "cmd.exe", args, root, "runas", 0
    If Err.Number <> 0 Then
        shell.Popup "Administrator privileges were not granted.", 0, "WiFiDrop", 16
    End If
    On Error GoTo 0
    WScript.Quit 0
End If

shell.Popup "Unknown WiFiDrop launcher mode.", 0, "WiFiDrop", 16
WScript.Quit 1
