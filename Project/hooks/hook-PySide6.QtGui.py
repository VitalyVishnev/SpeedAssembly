from PyInstaller.utils.hooks.qt import add_qt6_dependencies


hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
datas = [entry for entry in datas if "translations" not in entry[1].replace("\\", "/")]
