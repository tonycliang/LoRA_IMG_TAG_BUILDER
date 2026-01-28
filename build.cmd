@echo off
REM call venv\Scripts\activate.bat
python.exe -m nuitka ^
    --standalone ^
    --onefile ^
    --windows-console-mode=disable ^
    --windows-icon-from-ico=favicon.ico ^
    --include-data-file=favicon.ico=favicon.ico ^
    --output-dir=Release ^
    --remove-output ^
    --enable-plugin=tk-inter ^
    --windows-file-version=0.0.5 ^
    --windows-product-version=0.0.5 ^
    --windows-company-name="Tony" ^
    --windows-product-name="LoRA_IMG_TAG_BUILDER" ^
    LoRA_IMG_TAG_BUILDER.py

if %errorlevel% == 0 (
    echo.
    echo done
    echo.
) else (
    echo.
    echo error
    echo.
)

pause