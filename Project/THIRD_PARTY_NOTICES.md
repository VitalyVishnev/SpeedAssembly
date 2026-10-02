# Third-party notices

SpeedAssembly is MIT-licensed. Its Windows executable also contains or uses
third-party components under their own licenses. Those licenses do not change
the MIT license of SpeedAssembly's original source code.

## Runtime components

| Component | License | Compatibility and source |
| --- | --- | --- |
| Python | PSF License 2.0 | Permissive; [license](https://docs.python.org/3/license.html) |
| PySide6, Shiboken6, and Qt 6 | LGPL-3.0-only (used by this distribution) | Permits commercial and personal use. Qt libraries remain separately licensed and dynamically linked; [Qt for Python licensing](https://doc.qt.io/qtforpython-6/licenses.html) |
| NumPy | BSD-3-Clause, with bundled component licenses | Permissive; the distributed wheel includes OpenBLAS and its notices; [license](https://github.com/numpy/numpy/blob/main/LICENSE.txt) |
| fast-simplification | MIT | Permissive; copyright PyVista Developers; [license](https://github.com/pyvista/fast-simplification/blob/main/LICENSE) |
| Manifold | Apache-2.0 | Permissive; copyright Manifold contributors; [license](https://github.com/elalish/manifold/blob/master/LICENSE) |
| defusedxml | PSF License 2.0 | Permissive; [license](https://github.com/tiran/defusedxml/blob/main/LICENSE) |
| OpenUSD (`usd-core`) | Tomorrow Open Source Technology License 1.0 | Apache-2.0-derived permissive license; [license](https://github.com/PixarAnimationStudios/OpenUSD/blob/release/LICENSE.txt) |
| ufbx 0.21.3 | MIT or public domain | Permissive; vendored source and license are retained in `src/xml_to_usda/vendor/ufbx`; [license](https://github.com/ufbx/ufbx/blob/master/LICENSE) |
| PyInstaller | GPL-2.0-or-later with Bootloader Exception | The exception permits distribution of programs built with PyInstaller; [license](https://pyinstaller.org/en/stable/license.html) |

The installed distributions may contain additional notices for code bundled by
their upstream projects. Their complete corresponding license texts remain in
the source distributions linked above.

### Qt/PySide6 source offer

The application source and reproducible packaging scripts are available in the
[SpeedAssembly repository](https://github.com/VitalyVishnev/SpeedAssembly), so
recipients can rebuild the application with a compatible modified Qt/PySide6.
For at least three years after a binary release, any recipient may request the
complete corresponding source of the exact LGPL-covered Qt/PySide6/Shiboken6
version distributed with that release by opening a public
[GitHub issue](https://github.com/VitalyVishnev/SpeedAssembly/issues). It will
be supplied at no charge electronically, or for no more than the reasonable
physical cost if physical media is requested.

## ufbx

The FBX importer compiles vendored ufbx C source at revision
`83bc7cf44f76bc8622de63b809a42b5d557cd733` (v0.21.3). Its complete license
and provenance hashes are retained in `src/xml_to_usda/vendor/ufbx/`. The
release ZIP also includes the upstream license as `licenses/ufbx-LICENSE`.

## Users and redistributors

Anyone may use SpeedAssembly's MIT-licensed code, including for commercial
studio work, without a fee from the SpeedAssembly author. Redistributors must
retain `LICENSE` and this notice and comply with all third-party licenses.

These licenses cover software, not input SpeedTree/FBX assets or generated
assets owned by their respective rightsholders.
