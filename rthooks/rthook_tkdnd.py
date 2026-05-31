"""Runtime hook: fix tkdnd library loading in frozen Windows builds.

Root cause
----------
The tkdnd native Tcl extension (a .dll) is extracted by PyInstaller into a
subdirectory of _MEIPASS:

    _MEIPASS/tkinterdnd2/tkdnd/win64/tkdnd2xx.dll

When Tcl calls Windows LoadLibrary on that DLL, the loader searches for its
own dependencies (tcl86.dll, tk86.dll, etc.) in:

  1. The DLL's own directory  (_MEIPASS/tkinterdnd2/tkdnd/win64/)
  2. The process PATH
  3. Windows system directories

The Tcl/Tk DLLs live in _MEIPASS (root), which is NOT in any of those
locations at startup, so LoadLibrary fails with "couldn't load library".

Fix
---
Prepend _MEIPASS to PATH before anything imports tkinterdnd2. This ensures
the Tcl/Tk DLLs are found when the tkdnd DLL is loaded by Tcl.

We also call os.add_dll_directory() (Python 3.8+ Windows API) on _MEIPASS
and the tkdnd subdirectories for belt-and-suspenders coverage.
"""
import os
import sys

if hasattr(sys, "_MEIPASS") and sys.platform == "win32":
    _meipass = sys._MEIPASS

    # --- 1. Prepend _MEIPASS to PATH so LoadLibrary finds Tcl/Tk DLLs -----
    os.environ["PATH"] = _meipass + os.pathsep + os.environ.get("PATH", "")

    # --- 2. os.add_dll_directory() — Python 3.8+ explicit DLL search dirs --
    # This covers Python-level DLL loading; Tcl-level loading is handled by
    # PATH above, but adding these dirs here is belt-and-suspenders.
    _dirs_to_register = [_meipass]
    _tkdnd_root = os.path.join(_meipass, "tkinterdnd2", "tkdnd")
    if os.path.isdir(_tkdnd_root):
        _dirs_to_register.append(_tkdnd_root)
        try:
            for _sub in os.listdir(_tkdnd_root):
                _full = os.path.join(_tkdnd_root, _sub)
                if os.path.isdir(_full):
                    _dirs_to_register.append(_full)
        except OSError:
            pass  # permission denied or other OS error — skip subdirs

    for _d in _dirs_to_register:
        try:
            os.add_dll_directory(_d)
        except (AttributeError, OSError):
            pass  # Python < 3.8 or path doesn't exist — safe to skip
