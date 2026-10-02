"""PyInstaller collection hook for the OpenUSD modules used by Wind Preview."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs


hiddenimports = (
    "pxr.Ar",
    "pxr.Ar._ar",
    "pxr.Gf",
    "pxr.Gf._gf",
    "pxr.Kind",
    "pxr.Kind._kind",
    "pxr.Pcp",
    "pxr.Pcp._pcp",
    "pxr.Plug",
    "pxr.Plug._plug",
    "pxr.Sdf",
    "pxr.Sdf._sdf",
    "pxr.Tf",
    "pxr.Tf._tf",
    "pxr.Trace",
    "pxr.Trace._trace",
    "pxr.Ts",
    "pxr.Ts._ts",
    "pxr.Usd",
    "pxr.Usd._usd",
    "pxr.UsdGeom",
    "pxr.UsdGeom._usdGeom",
    "pxr.UsdSkel",
    "pxr.UsdSkel._usdSkel",
    "pxr.Vt",
    "pxr.Vt._vt",
    "pxr.Work",
    "pxr.Work._work",
)
binaries = [
    item
    for item in collect_dynamic_libs("pxr")
    if Path(item[0]).name.casefold() in {"tbb.dll", "usd_ms.dll"}
]
datas = collect_data_files("pxr", includes=["pluginfo/**"])
