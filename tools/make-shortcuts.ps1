# Creates "Swiss RU-DE" shortcuts on the desktop and in the Start menu.
param([Parameter(Mandatory = $true)][string]$Root)

$shell = New-Object -ComObject WScript.Shell
$target = Join-Path $Root ".venv\Scripts\swiss-ru-de-gui.exe"
$icon = Join-Path $Root "swiss_ru_de\icon.ico"
$folders = @([Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("Programs"))
foreach ($folder in $folders) {
    $link = $shell.CreateShortcut((Join-Path $folder "Swiss RU-DE.lnk"))
    $link.TargetPath = $target
    $link.WorkingDirectory = $Root
    $link.IconLocation = $icon
    $link.Description = "Swiss German -> Russian / German live subtitles"
    $link.Save()
}
Write-Host "      Shortcuts created: desktop and Start menu ('Swiss RU-DE')."
