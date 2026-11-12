@echo off
rem Builds both sides natively on Windows: clang++ (LLVM) against the MSVC runtime, STL and SDK, and cargo release.
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul || exit /b 1
set PATH=C:\Program Files\LLVM\bin;C:\Program Files\CMake\bin;%LOCALAPPDATA%\Microsoft\WinGet\Links;%USERPROFILE%\.cargo\bin;%PATH%
echo VCToolsVersion=%VCToolsVersion%
cd /d "%~dp0"
cmake -S cpp -B cpp\build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_COMPILER=clang++ || exit /b 1
cmake --build cpp\build || exit /b 1
cd rust
cargo build --release || exit /b 1
