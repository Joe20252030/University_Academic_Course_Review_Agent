"""Runtime hook: fix tkdnd library loading in frozen Windows builds.

Root cause
----------
tkinterdnd2's ``_require()`` adds the tkdnd directory to Tcl's ``auto_path``
by calling ``lappend auto_path module_path`` from Python.  In a frozen build
the Tcl interpreter is already initialised, and on some Windows/Tcl builds the
package-index scan completes before the ``lappend`` arrives.

Fix (three-layer approach)
--------------------------
1. **TCLLIBPATH** (Tcl-native, most reliable)
   Tcl reads this environment variable at interpreter startup and prepends its
   entries to ``auto_path`` before any package-index scan.  Setting it here
   (before Python/Tk starts) ensures the tkdnd ``pkgIndex.tcl`` is found
   during the very first ``package require tkdnd`` call.  The value is a
   Tcl list (space-separated); each path is brace-quoted so that directory
   names containing spaces (e.g. ``C:\Users\John Smith\…``) are treated as
   a single list element by the Tcl parser.

2. **PATH prepend** — Tcl's ``load`` on Windows uses ``LoadLibrary``.  The DLL
   loader searches PATH for implicit dependencies of the tkdnd DLL (tcl86.dll,
   tk86.dll, etc. which live in ``_MEIPASS``).  Prepending ``_MEIPASS`` to PATH
   ensures those DLLs are found.

3. **os.add_dll_directory()** — Python 3.8+ explicit DLL search-path API.
   Belt-and-suspenders for Python-level DLL loading; Tcl-level loading is
   handled by PATH above.
"""
import os
import sys

if hasattr(sys, "_MEIPASS") and sys.platform == "win32":
    _meipass = sys._MEIPASS

    # Determine the platform subdirectory (mirrors _require() logic).
    _machine = os.environ.get("PROCESSOR_ARCHITECTURE", "AMD64")
    if _machine == "ARM64":
        _subdir = "win-arm64"
    elif _machine in ("AMD64", "x86_64"):
        _subdir = "win-x64"
    else:
        _subdir = "win-x86"
    _tkdnd_dir = os.path.join(_meipass, "tkinterdnd2", "tkdnd", _subdir)

    # ── 1. TCLLIBPATH — pre-configure Tcl's auto_path at interpreter start ──
    # Brace-quote the path so Tcl treats it as a single list element even
    # when the directory name contains spaces (e.g. "C:/Users/John Smith/…").
    # Forward slashes are used because Tcl's file handling prefers them on
    # Windows; backslashes inside braces are interpreted literally by Tcl.
    if os.path.isdir(_tkdnd_dir):
        _curr_tcllib = os.environ.get("TCLLIBPATH", "")
        _quoted = "{" + _tkdnd_dir.replace("\\", "/").replace("}", r"\}") + "}"
        os.environ["TCLLIBPATH"] = (
            _quoted + (" " + _curr_tcllib if _curr_tcllib else "")
        )

    # ── 2. PATH prepend — DLL dependency resolution for LoadLibrary ─────────
    os.environ["PATH"] = _meipass + os.pathsep + os.environ.get("PATH", "")

    # ── 3. os.add_dll_directory() — explicit DLL search dirs (Python 3.8+) ──
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
            pass

    for _d in _dirs_to_register:
        try:
            os.add_dll_directory(_d)
        except (AttributeError, OSError):
            pass
