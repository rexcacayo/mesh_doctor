# SPDX-FileCopyrightText: 2026 Ricardo Lugaresi
# SPDX-License-Identifier: GPL-3.0-or-later

"""Crea dist/<paquete>-<versión>.zip listo para «Instalar desde disco»."""
import zipfile
from pathlib import Path
here = Path(__file__).resolve().parent
pkg = here / 'mesh_doctor'
version = '1.0.2'
out = here / 'dist' / f'{pkg.name}-{version}.zip'
out.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    for f in sorted(pkg.rglob('*')):
        if f.is_file() and '__pycache__' not in f.parts:
            z.write(f, f.relative_to(here))
print(out)
