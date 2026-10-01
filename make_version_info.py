"""Gera version_info.txt (metadados do .exe: empresa, descrição, versão, licença).

Um executável sem esses metadados parece anônimo para os antivírus e é um dos
motivos mais comuns de falso positivo. Rode antes do PyInstaller:

    python make_version_info.py
    python -m PyInstaller --onefile --windowed --noupx --name ClickForge ^
        --icon icon.ico --version-file version_info.txt clickforge.py
"""
import re

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
)

with open("clickforge.py", encoding="utf-8") as f:
    version = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', f.read(), re.M).group(1)

parts = [int(p) for p in version.split(".")] + [0, 0, 0, 0]
nums = tuple(parts[:4])

info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=nums, prodvers=nums, mask=0x3F, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0),
    kids=[
        StringFileInfo([
            StringTable("040904B0", [
                StringStruct("CompanyName", "Rhuan De Cillo Silva"),
                StringStruct("FileDescription", "ClickForge - autoclicker de codigo aberto"),
                StringStruct("FileVersion", version),
                StringStruct("InternalName", "ClickForge"),
                StringStruct("LegalCopyright", "MIT License - Copyright (c) 2026 Rhuan De Cillo Silva"),
                StringStruct("OriginalFilename", "ClickForge.exe"),
                StringStruct("ProductName", "ClickForge"),
                StringStruct("ProductVersion", version),
                StringStruct("Comments", "https://github.com/LuaMastery/ClickForge"),
            ])
        ]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)

with open("version_info.txt", "w", encoding="utf-8") as f:
    f.write(str(info))
print("version_info.txt gerado para", version)
