@echo off
setlocal

set "SOURCE_DIR=C:\Users\anson\Desktop\weatherData"
set "DEST_DIR=C:\Users\anson\Desktop\weatherData\weatherMake"

if not exist "%DEST_DIR%" mkdir "%DEST_DIR%"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$source = '%SOURCE_DIR%';" ^
  "$dest = '%DEST_DIR%';" ^
  "$zips = Get-ChildItem -LiteralPath $source -File -Filter '*.zip' | Sort-Object Name;" ^
  "if ($zips.Count -eq 0) { Write-Host 'No zip files found in:' $source; exit 0 }" ^
  "Write-Host ('Found ' + $zips.Count + ' zip files.');" ^
  "foreach ($zip in $zips) {" ^
  "  $out = Join-Path $dest $zip.BaseName;" ^
  "  New-Item -ItemType Directory -Path $out -Force | Out-Null;" ^
  "  Write-Host ('Extracting ' + $zip.Name);" ^
  "  Expand-Archive -LiteralPath $zip.FullName -DestinationPath $out -Force;" ^
  "}" ^
  "Write-Host '';" ^
  "Write-Host ('Done. Files were extracted into: ' + $dest);"

echo.
pause
