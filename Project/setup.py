import os
from pathlib import Path

from setuptools import Extension, find_packages, setup


compile_args = ["/O2"] if os.name == "nt" else ["-O2"]

if os.name == "nt":
    # CPython 3.10's `vcvarsall && set` parser accepts both `PATH` and the
    # inherited `Path` as the same key. On this workstation the latter comes
    # last and drops MSVC's bin directory, so distutils cannot spawn cl.exe.
    import distutils._msvccompiler as _msvccompiler

    _get_vc_env = _msvccompiler._get_vc_env

    def _get_repaired_vc_env(plat_spec: str):
        environment = _get_vc_env(plat_spec)
        tool_root = environment.get("vctoolsinstalldir")
        if tool_root:
            compiler_dirs = [
                Path(tool_root) / "bin" / host / "x64"
                for host in ("Hostx86", "Hostx64")
            ]
            sdk_bin_root = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Windows Kits" / "10" / "bin"
            sdk_bins = sorted(
                (directory / "x86" for directory in sdk_bin_root.iterdir() if directory.is_dir()),
                reverse=True,
            ) if sdk_bin_root.is_dir() else []
            available = [str(directory) for directory in (*compiler_dirs, *sdk_bins) if directory.is_dir()]
            if available:
                environment["path"] = os.pathsep.join((
                    *available,
                    environment.get("path", ""),
                ))
        return environment

    _msvccompiler._get_vc_env = _get_repaired_vc_env

setup(
    packages=find_packages("src"),
    package_dir={"": "src"},
    ext_modules=[
        Extension(
            "xml_to_usda._ufbx",
            sources=[
                "src/xml_to_usda/_ufbx.c",
                "src/xml_to_usda/vendor/ufbx/ufbx.c",
            ],
            include_dirs=["src/xml_to_usda/vendor/ufbx"],
            extra_compile_args=compile_args,
        )
    ]
)
