@echo off
chcp 65001 >nul
title 局域网快传服务

echo 正在启动快传服务，请稍候...

:: 核心优化：利用 %~dp0 动态获取当前文件夹路径，彻底免去手动填写绝对路径，消除隐私风险！
cd /d "%~dp0"

:: 先让 Python 服务在后台跑起来
start /b python app.py

:: 等待 2 秒钟，让服务器有时间准备好
timeout /t 2 >nul

:: 自动呼出电脑默认浏览器并打开网页
start http://127.0.0.1:5000

echo 服务已启动！请勿关闭此黑窗口，不用时直接按右上角 X 即可。
pause >nul