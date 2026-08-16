# 打包脚本（Windows）：构建前端并打进 Spring Boot fat jar
# 产物：target/QuanForge-springboot-0.0.1-SNAPSHOT.jar（单文件即整个应用，可部署到任意 JRE21 机器）
# 用法：.\package.ps1

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

Write-Host "== 1/3 构建前端 ==" -ForegroundColor Cyan
Push-Location "$root/frontend"
pnpm build
if ($LASTEXITCODE -ne 0) { throw "前端构建失败" }
Pop-Location

Write-Host "== 2/3 拷贝静态资源 ==" -ForegroundColor Cyan
$static = "$root/src/main/resources/static"
Remove-Item $static -Recurse -Force -ErrorAction SilentlyContinue
New-Item $static -ItemType Directory -Force | Out-Null
Copy-Item "$root/frontend/dist/*" $static -Recurse -Force
Write-Host "已拷贝 $((Get-ChildItem $static -Recurse -File | Measure-Object).Count) 个文件到 static/"

Write-Host "== 3/3 Maven 打包 ==" -ForegroundColor Cyan
Push-Location $root
& .\mvnw.cmd -q -DskipTests package
if ($LASTEXITCODE -ne 0) { throw "Maven 打包失败" }
Pop-Location

$jar = Get-ChildItem "$root/target/*.jar" | Where-Object { $_.Name -notmatch "^\." -and $_.Name -notmatch "-original" } | Select-Object -First 1
Write-Host "完成: $($jar.FullName) ($([math]::Round($jar.Length/1MB, 1)) MB)" -ForegroundColor Green
