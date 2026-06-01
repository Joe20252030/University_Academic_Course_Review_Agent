"""Runtime hook: fix tkdnd loading in frozen macOS builds.

Root cause
----------
tkinterdnd2's ``_require()`` adds the tkdnd directory to Tcl's ``auto_path``
by calling ``lappend auto_path module_path`` from Python.  In a frozen build
the Tcl interpreter is already initialised by the time ``_require()`` runs,
and on some macOS/Tcl builds the initial package-index scan has already
completed.  That scan never saw the tkdnd directory, so ``package require tkdnd``
fails even after the ``lappend``.

Fix (two-layer approach)
------------------------
1. **TCLLIBPATH** (Tcl-native, most reliable)
   Tcl reads this environment variable at interpreter *startup* — before any
   package-index scanning — and prepends its entries to ``auto_path``.
   Setting it in this runtime hook (which runs before Python starts) ensures
   the tkdnd directory is in Tcl's ``auto_path`` from the very first moment
   the interpreter initialises.  This is the primary fix.

   ``TCLLIBPATH`` uses *space*-separated paths (Tcl list syntax, not ``:``)
   and must be set before ``Tk.__init__()`` is called.  Each path is
   brace-quoted so that directory names containing spaces are treated as a
   single list element by the Tcl parser.

2. **DYLD_FALLBACK_LIBRARY_PATH** (belt-and-suspenders)
   Keeps ``_MEIPASS`` and all tkdnd subdirectories in the dynamic-linker
   fallback search path so ``dlopen()`` can find any dylib dependencies when
   Tcl calls ``load libtkdnd2.9.3.dylib``.  Not the primary mechanism —
   the dylib's own deps are system frameworks — but retained for robustness.

freeze_support()
----------------
Not called here — runtime hooks run before ``__main__``.  ``freeze_support()``
belongs in ``__main__.py`` where it already lives.
"""
import os
import platform
import sys

if hasattr(sys, "_MEIPASS") and sys.platform == "darwin":
    _meipass = sys._MEIPASS

    # Determine the correct platform subdirectory (mirrors _require() logic).
    _machine = platform.machine()
    _subdir = "osx-arm64" if _machine == "arm64" else "osx-x64"
    _tkdnd_dir = os.path.join(_meipass, "tkinterdnd2", "tkdnd", _subdir)

    # ── 1. TCLLIBPATH — pre-configure Tcl's auto_path at interpreter start ──
    # Tcl reads TCLLIBPATH at startup and prepends each entry to auto_path
    # BEFORE the first package-index scan.  This is the most reliable way to
    # ensure ``package require tkdnd`` finds pkgIndex.tcl without depending on
    # the _require() lappend arriving in time.
    # Brace-quote the path so that any spaces in the directory name are
    # treated as part of the path, not as list-element separators.
    if os.path.isdir(_tkdnd_dir):
        _curr_tcllib = os.environ.get("TCLLIBPATH", "")
        _quoted = "{" + _tkdnd_dir.replace("}", r"\}") + "}"
        os.environ["TCLLIBPATH"] = (
            _quoted + (" " + _curr_tcllib if _curr_tcllib else "")
        )

    # ── 2. DYLD_FALLBACK_LIBRARY_PATH — dylib dependency resolution ─────────
    # Belt-and-suspenders: ensures _MEIPASS root and all tkdnd subdirectories
    # are in the fallback dylib search path for dlopen().  The tkdnd dylib
    # only depends on macOS system frameworks (Cocoa, AppKit, etc.), so this
    # is mostly defensive.
    _extra: list[str] = [_meipass]
    _tkdnd_root = os.path.join(_meipass, "tkinterdnd2", "tkdnd")
    if os.path.isdir(_tkdnd_root):
        _extra.append(_tkdnd_root)
        try:
            for _sub in os.listdir(_tkdnd_root):
                _full = os.path.join(_tkdnd_root, _sub)
                if os.path.isdir(_full):
                    _extra.append(_full)
        except OSError:
            pass

    _current = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = (
        os.pathsep.join(_extra) + (os.pathsep + _current if _current else "")
    )
