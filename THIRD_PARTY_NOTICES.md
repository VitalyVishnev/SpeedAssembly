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

## Autodesk FBX SDK

The packaged FBX import path currently embeds Autodesk FBX SDK binary code.
Autodesk FBX SDK is proprietary and is **not** licensed under the SpeedAssembly
MIT License. Its use and redistribution are governed exclusively by the
Autodesk license supplied with SDK 2020.3.4. The MIT grant applies to
SpeedAssembly's original code, not to Autodesk code.

This software contains Autodesk® FBX® code developed by Autodesk, Inc.
Copyright 2019 Autodesk, Inc. All rights reserved. Such code is provided "as is"
and Autodesk, Inc. disclaims any and all warranties, whether express or
implied, including without limitation the implied warranties of
merchantability, fitness for a particular purpose or non-infringement of third
party rights. In no event shall Autodesk, Inc. be liable for any direct,
indirect, incidental, special, exemplary, or consequential damages (including,
but not limited to, procurement of substitute goods or services; loss of use,
data, or profits; or business interruption) however caused and on any theory
of liability, whether in contract, strict liability, or tort (including
negligence or otherwise) arising in any way out of such code.

Autodesk and FBX are registered trademarks or trademarks of Autodesk, Inc.,
and/or its subsidiaries and/or affiliates in the United States and/or other
countries. No endorsement by Autodesk is implied.

## Users and redistributors

Anyone may use SpeedAssembly's MIT-licensed code, including for commercial
studio work, without a fee from the SpeedAssembly author. Redistributors must
retain `LICENSE` and this notice and comply with all third-party licenses.
Until Autodesk confirms the applicable redistribution terms in writing, do not
redistribute a binary containing the Autodesk FBX SDK under the claim that the
entire binary is MIT-licensed. A public binary release must either carry that
permission or distribute the FBX backend separately under its Autodesk terms.

These licenses cover software, not input SpeedTree/FBX assets or generated
assets owned by their respective rightsholders.
