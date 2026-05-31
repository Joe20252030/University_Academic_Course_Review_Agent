"""Runtime hook: fix tkdnd dylib loading in frozen macOS builds.

Root cause
----------
The tkdnd Tcl extension (a .dylib) is extracted into a subdirectory:

    _MEIPASS/tkinterdnd2/tkdnd/osx-arm64/  (Apple Silicon)
    _MEIPASS/tkinterdnd2/tkdnd/osx-x64/    (Intel)

When Tcl loads that dylib, macOS's dynamic linker resolves its own
dependencies (tcl86.dylib, tk86.dylib, libtcl*.dylib, etc.) by looking in:

  1. Absolute paths / @rpath / @loader_path embedded in the dylib
  2. DYLD_LIBRARY_PATH
  3. DYLD_FALLBACK_LIBRARY_PATH
  4. Default system locations

PyInstaller's bootloader sets DYLD_LIBRARY_PATH to _MEIPASS via a re-exec
trick.  However, in some macOS/SIP configurations that re-exec path is
bypassed and DYLD_LIBRARY_PATH may not cover _MEIPASS reliably.

Fix
---
This runtime hook runs before any application code and explicitly sets
DYLD_FALLBACK_LIBRARY_PATH to include _MEIPASS and the tkdnd architecture
subdirectory.  Using the FALLBACK variant avoids clobbering any paths already
placed in DYLD_LIBRARY_PATH by the PyInstaller bootloader.

freeze_support()
----------------
On macOS, multiprocessing defaults to the 'spawn' start method (Python 3.8+).
When the frozen binary spawns worker processes (e.g. onnxruntime, tokenizers),
those workers re-execute the binary.  multiprocessing.freeze_support() is
called in __main__.py to intercept that re-execution and act as a worker
rather than running main() again.  This hook does NOT call freeze_support()
because runtime hooks run before __main__ and calling it here would be too
early; it belongs in __main__.py.
"""
import os
import sys

if hasattr(sys, "_MEIPASS") and sys.platform == "darwin":
    _meipass = sys._MEIPASS

    # Collect directories to add: _MEIPASS root + tkdnd subdirectories
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
            pass  # permission denied or other OS error — skip subdirs

    # Prepend to DYLD_FALLBACK_LIBRARY_PATH (does not override bootloader's
    # DYLD_LIBRARY_PATH, so the two complement each other).
    _current = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = (
        os.pathsep.join(_extra) + (os.pathsep + _current if _current else "")
    )
