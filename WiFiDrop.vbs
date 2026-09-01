Option Explicit

Dim mode, shellApp, shell, fso, root, batPath, args, q, message
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
q = Chr(34)

If WScript.Arguments.Count = 0 Then
    mode = "elevate"
    batPath = root & "\run_gui.bat"
Else
    mode = LCase(WScript.Arguments(0))
End If

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
    ElseIf Len(batPath) = 0 Then
        batPath = root & "\run_gui.bat"
    End If

    Set shellApp = CreateObject("Shell.Application")
    args = "/d /s /c " & q & q & batPath & q & " --elevated" & q
    On Error Resume Next
    shellApp.ShellExecute "cmd.exe", args, root, "runas", 0
    If Err.Number <> 0 Then
        shell.Popup "Administrator privileges are required to run WiFiDrop.", 0, "WiFiDrop", 16
    End If
    On Error GoTo 0
    WScript.Quit 0
End If

shell.Popup "Unknown WiFiDrop launcher mode.", 0, "WiFiDrop", 16
WScript.Quit 1
