# PyInstaller spec - build from the repository root:  pyinstaller desktop/swing_desktop.spec
from PyInstaller.utils.hooks import collect_submodules

hidden = collect_submodules("uvicorn") + collect_submodules("app") + ["webview"]

a = Analysis(
    ["desktop_app.py"],
    pathex=["../backend"],
    datas=[("../frontend", "frontend"), ("../data/universe.json", "data"),
           ("../data/reference_live.example.json", "data")],
    hiddenimports=hidden,
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="SwingWatchlistAI", console=False,
          icon=None)
coll = COLLECT(exe, a.binaries, a.datas, name="SwingWatchlistAI")
