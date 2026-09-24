@echo off
rem 一键启动 EasyEDA 桥接服务(幂等: 已在运行会提示)
set SKILL=%USERPROFILE%\.dsh\skills\easyeda-api
node "%SKILL%\scriptsridge-server.mjs"
pause
