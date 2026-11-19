@echo off
setlocal

set "REPO_ROOT=%~dp0.."
pushd "%REPO_ROOT%" || (
    echo Failed to open the repository directory.
    exit /b 1
)

set "VENV_PYTHON=%CD%\.venv\Scripts\python.exe"
if not exist "%VENV_PYTHON%" (
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3 -m venv "%CD%\.venv"
    ) else (
        where python >nul 2>nul
        if errorlevel 1 (
            echo Python 3 was not found. Install Python 3 and try again.
            popd
            exit /b 1
        )
        python -m venv "%CD%\.venv"
    )
    if errorlevel 1 (
        echo Unable to create the project virtual environment.
        popd
        exit /b 1
    )
)

"%VENV_PYTHON%" -c "import flask, psutil, argon2, cryptography" >nul 2>nul
if errorlevel 1 (
    echo Installing application dependencies...
    "%VENV_PYTHON%" -m pip install -r "%CD%\requirements.txt"
    if errorlevel 1 (
        echo Dependency installation failed.
        popd
        exit /b 1
    )
)

if not exist "app\data" mkdir "app\data"
if errorlevel 1 (
    echo Unable to create app\data.
    popd
    exit /b 1
)

echo Starting MCManager at http://127.0.0.1:5000
"%VENV_PYTHON%" -m flask --app "app:create_app(database_path='app/data/manager.db', keyfile_path='app/data/secrets.key', migrations_dir='migrations')" run --host 127.0.0.1 --port 5000
set "EXIT_CODE=%ERRORLEVEL%"

popd
exit /b %EXIT_CODE%
