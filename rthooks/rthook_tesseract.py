# -*- coding: utf-8 -*-
"""Runtime hook: configure pytesseract to use the Tesseract binary bundled
inside the PyInstaller _MEIPASS directory.

Strategy
--------
1. TESSDATA_PREFIX  -- Tcl/Tesseract reads this env var to locate its language
   data files (eng.traineddata etc.).  Set it to _MEIPASS/tessdata/ so the
   bundled data is found regardless of what is (or is not) installed on the
   user's machine.

2. PATH prepend  -- On macOS the tesseract binary lives directly in _MEIPASS.
   Prepending _MEIPASS ensures the OS can exec it without an absolute path.
   On Windows the binary is also in _MEIPASS; PATH is updated identically.

3. pytesseract.tesseract_cmd  -- pytesseract uses this attribute for the
   explicit binary path.  Setting it here (before any import of pytesseract
   in application code) avoids the need for every call site to configure it.

The hook is a no-op when running from source (sys._MEIPASS is absent) or
when pytesseract is not installed.
"""
import os
import sys

if hasattr(sys, "_MEIPASS"):
    _meipass = sys._MEIPASS

    # -- 1. TESSDATA_PREFIX -----------------------------------------------
    _tessdata = os.path.join(_meipass, "tessdata")
    if os.path.isdir(_tessdata):
        os.environ["TESSDATA_PREFIX"] = _tessdata

    # -- 2. PATH prepend --------------------------------------------------
    _sep = ";" if sys.platform.startswith("win") else ":"
    os.environ["PATH"] = _meipass + _sep + os.environ.get("PATH", "")

    # -- 3. pytesseract binary path ---------------------------------------
    _tess_bin = (
        os.path.join(_meipass, "tesseract.exe")
        if sys.platform.startswith("win")
        else os.path.join(_meipass, "tesseract")
    )
    if os.path.isfile(_tess_bin):
        try:
            import pytesseract as _pyt
            _pyt.pytesseract.tesseract_cmd = _tess_bin
        except ImportError:
            pass   # pytesseract not in this build -- safe to ignore
