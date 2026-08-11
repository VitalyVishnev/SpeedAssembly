@echo off
setlocal

set "REPO_ROOT=%~dp0.."
set "PYTHON_EXE=%REPO_ROOT%\.venv310\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo Missing canonical Python environment: %PYTHON_EXE%
    echo Create .venv310 before previewing the documentation.
    exit /b 1
)

"%PYTHON_EXE%" -c "import mkdocs" >nul 2>&1
if errorlevel 1 (
    echo Documentation dependencies are not installed.
    echo Run: "%PYTHON_EXE%" -m pip install -r "%REPO_ROOT%\requirements-docs.txt"
    exit /b 1
)

pushd "%REPO_ROOT%"
"%PYTHON_EXE%" -m mkdocs serve --open
set "EXIT_CODE=%ERRORLEVEL%"
popd

exit /b %EXIT_CODE%
