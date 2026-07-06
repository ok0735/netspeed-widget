@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM 优先用 Python 3.10 的 pythonw 运行 pyw 脚本（包含 psutil 模块）
set PYTHONW_PATH=C:\Users\86139\AppData\Local\Programs\Python\Python310\pythonw.exe
if exist "%PYTHONW_PATH%" (
    start "" "%PYTHONW_PATH%" desktop_widget.pyw
    exit
)

REM 回退：运行编译版 exe
start "" netspeed.exe
exit
