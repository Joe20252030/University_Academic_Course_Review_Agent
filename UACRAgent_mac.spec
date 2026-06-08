# UACRAgent_mac.spec  — PyInstaller build spec for macOS
# Run with:  pyinstaller UACRAgent_mac.spec
# ---------------------------------------------------------------------------
import sys
from pathlib import Path

# Read the canonical version from pyproject.toml so the .app bundle always
# matches the package version without any manual sync step.
if sys.version_info >= (3, 11):
    import tomllib as _tomllib
else:
    try:
        import tomllib as _tomllib          # 3.11+ stdlib
    except ImportError:
        import tomli as _tomllib            # pip install tomli  (3.10 backport)
with open(Path(SPECPATH) / "pyproject.toml", "rb") as _f:
    _APP_VERSION: str = _tomllib.load(_f)["project"]["version"]
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_all, copy_metadata

block_cipher = None
HERE = Path(SPECPATH)       # directory this .spec file lives in

# ---------------------------------------------------------------------------
# 1. Collect data files and hidden imports from heavy packages
# ---------------------------------------------------------------------------
datas         = []
binaries      = []
hiddenimports = []

for pkg in [
    "langchain",
    "langchain_core",
    "langchain_community",
    "langchain_text_splitters",
    "langchain_google_genai",
    "langchain_openai",
    "langchain_huggingface",
    "langchain_chroma",
    "chromadb",
    "sentence_transformers",
    "tokenizers",
    "huggingface_hub",
    # Local embedding in the frozen .app uses Chroma's built-in ONNX path for
    # all-MiniLM-L6-v2. The broader sentence-transformers model list remains
    # source-mode only because PyTorch is not reliable enough in the packaged app.
    "onnxruntime",    # primary local-embedding runtime in frozen .app
    "torch",          # kept for source-mode / future support
    "transformers",   # kept for source-mode / future support
]:
    try:
        d, b, h = collect_all(pkg)
        datas         += d
        binaries      += b
        hiddenimports += h
    except Exception as _e:
        print(f"WARNING: collect_all('{pkg}') failed: {_e} — skipping.")

# torch hidden imports that the hook sometimes misses
hiddenimports += [
    "torch",
    "torch._C",
    "torch.nn",
    "torch.nn.functional",
    "torch.utils",
    "torch.utils.data",
]

# tiktoken encodings (needed by langchain_openai)
datas         += collect_data_files("tiktoken")
datas         += collect_data_files("tiktoken_ext")
hiddenimports += ["tiktoken_ext.openai_public", "tiktoken_ext.cl100k_base"]

# pydantic v2
hiddenimports += collect_submodules("pydantic")
hiddenimports += collect_submodules("pydantic_settings")

# PIL
datas         += collect_data_files("PIL")
hiddenimports += collect_submodules("PIL")

# fpdf2
datas += collect_data_files("fpdf")

# python-docx / docx2txt
datas += collect_data_files("docx")

# python-pptx (PowerPoint support)
try:
    datas         += collect_data_files("pptx")
    hiddenimports += collect_submodules("pptx")
    hiddenimports += ["pptx", "pptx.util", "pptx.presentation",
                      "pptx.shapes.autoshape", "pptx.shapes.picture"]
except Exception as _e:
    print(f"WARNING: python-pptx collection failed: {_e}")

# pytesseract
hiddenimports += ["pytesseract"]

# certifi — CA bundle used by updater.py for HTTPS in frozen macOS builds.
# PyInstaller's frozen app cannot reach the system certificate store, so
# urllib raises CERTIFICATE_VERIFY_FAILED without this.
datas         += collect_data_files("certifi")
hiddenimports += ["certifi"]

# uacragent dist-info — lets importlib.metadata.version("uacragent") resolve
# the correct version string inside the frozen app.  Without this,
# PackageNotFoundError is raised, the pyproject.toml fallback also fails
# (the file is not inside _MEIPASS), and _running_version() returns "0.0.0".
datas         += copy_metadata("uacragent")

# ---------------------------------------------------------------------------
# Tesseract binary + language data (for image OCR in .pptx slides)
# ---------------------------------------------------------------------------
# Strategy: locate the Tesseract binary installed on the BUILD machine and
# bundle it alongside its tessdata directory.  Only the English language pack
# (eng.traineddata) is included to keep the bundle lean; add more .traineddata
# files here if additional language support is needed.
#
# Expected Homebrew locations:
#   Apple Silicon : /opt/homebrew/bin/tesseract  + /opt/homebrew/share/tessdata/
#   Intel Mac     : /usr/local/bin/tesseract    + /usr/local/share/tessdata/
#
# rthook_tesseract.py configures TESSDATA_PREFIX and pytesseract.tesseract_cmd
# at runtime so application code never needs to know the bundled path.

import shutil as _shutil
_tess_bin = (
    _shutil.which("tesseract")
    or "/opt/homebrew/bin/tesseract"
    or "/usr/local/bin/tesseract"
)
_tess_bin_path = Path(_tess_bin) if _tess_bin and Path(_tess_bin).is_file() else None

if _tess_bin_path:
    binaries += [(str(_tess_bin_path), ".")]
    # Tessdata directory: resolve relative to binary location.
    _possible_tessdata = [
        _tess_bin_path.parent.parent / "share" / "tessdata",  # Homebrew
        Path("/usr/share/tessdata"),                            # macOS system
        Path("/usr/local/share/tessdata"),                      # Homebrew Intel
    ]
    _tessdata_dir = next(
        (p for p in _possible_tessdata if (p / "eng.traineddata").is_file()),
        None,
    )
    if _tessdata_dir:
        # Bundle only English by default; add more traineddata files here if needed.
        _eng_data = _tessdata_dir / "eng.traineddata"
        datas += [(str(_eng_data), "tessdata")]
        print(f"INFO: Bundling Tesseract from {_tess_bin_path}, tessdata from {_tessdata_dir}")
    else:
        print("WARNING: eng.traineddata not found — OCR will be unavailable in the built app.")
else:
    print("WARNING: tesseract binary not found on PATH or in Homebrew locations.")
    print("         Install with:  brew install tesseract")
    print("         OCR on PPTX image slides will be unavailable in the built app.")

# tkinterdnd2 — bundle the platform-specific tkdnd extension correctly.
#
# Both the dylib AND the .tcl scripts go into datas, not binaries.
#
# Why datas for the dylib?
#   PyInstaller's binary pipeline (macholib) does NOT guarantee that a dylib
#   with a bare install name (no @rpath / @loader_path prefix) lands at the
#   dest_dir we specify — it may be relocated to _MEIPASS root, while
#   pkgIndex.tcl still points to the subdirectory.  Tcl's `load $dir/$lib`
#   then fails with "couldn't load file" even though the file exists elsewhere.
#
#   Crucially, the tkdnd dylib ships from the tkinterdnd2 wheel already signed
#   with an adhoc,linker-signed signature (Apple ld at build time).  That
#   signature is valid for dlopen() in any unsigned or ad-hoc–signed process,
#   so PyInstaller re-signing is unnecessary.
#
#   Placing it in datas guarantees it lands at exactly
#       _MEIPASS/tkinterdnd2/tkdnd/<arch>/libtkdnd*.dylib
#   which is where pkgIndex.tcl's `load $dir/$lib` resolves it.
#
# The TCLLIBPATH env-var (set in rthook_tkdnd_mac.py before Python starts)
# is the primary mechanism that gets pkgIndex.tcl into Tcl's auto_path before
# the first `package require tkdnd` call; the `lappend auto_path` in
# tkinterdnd2._require() is belt-and-suspenders.
#
# We only bundle the current-machine platform subdirectory to keep the bundle
# lean and to avoid bundling ARM dylibs on Intel (which would be ignored anyway).
import platform as _plat
import tkinterdnd2 as _tkdnd

_tkdnd_pkg_dir  = Path(_tkdnd.__file__).parent
_tkdnd_machine  = _plat.machine()
_tkdnd_subdir   = "osx-arm64" if _tkdnd_machine == "arm64" else "osx-x64"
_tkdnd_plat_dir = _tkdnd_pkg_dir / "tkdnd" / _tkdnd_subdir

if _tkdnd_plat_dir.is_dir():
    _tkdnd_dest = f"tkinterdnd2/tkdnd/{_tkdnd_subdir}"
    # Dylib → datas (exact placement guaranteed; original adhoc signature preserved)
    for _f in _tkdnd_plat_dir.glob("*.dylib"):
        datas += [(str(_f), _tkdnd_dest)]
    # Tcl scripts → datas (plain text, no signing needed)
    for _f in _tkdnd_plat_dir.glob("*.tcl"):
        datas += [(str(_f), _tkdnd_dest)]
else:
    print(f"WARNING: tkdnd platform dir not found: {_tkdnd_plat_dir}")

# Python module files (__init__.py, TkinterDnD.py) → collected automatically
# by PyInstaller's module analysis.  No explicit datas entry needed.

# ---------------------------------------------------------------------------
# 2. Our own package data files
# ---------------------------------------------------------------------------
datas += [
    (str(HERE / "src" / "uacragent" / "assets"),           "uacragent/assets"),
    (str(HERE / "src" / "uacragent" / "agent" / "prompts"), "uacragent/agent/prompts"),
]

# ---------------------------------------------------------------------------
# 3. Our own modules (ensure none are accidentally excluded)
# ---------------------------------------------------------------------------
hiddenimports += [
    # ── ui ────────────────────────────────────────────────────────────────
    "uacragent",
    "uacragent.ui.desktop.app",
    "uacragent.ui.desktop._appearance_mixin",
    "uacragent.ui.desktop._settings_mixin",
    "uacragent.ui.desktop._chat_mixin",
    "uacragent.ui.desktop._session_mixin",
    "uacragent.ui.desktop._ui_constants",
    "uacragent.ui.desktop._custom_widgets",   # critical — imported at top of app.py
    # ── agent ─────────────────────────────────────────────────────────────
    "uacragent.agent.conversation",
    "uacragent.agent.session",
    "uacragent.agent.pipeline",               # core RAG pipeline
    "uacragent.agent.reasoning",              # imported by pipeline
    "uacragent.agent.service",
    "uacragent.agent.workspace_manager",      # wipe helpers used by _chat_mixin
    "uacragent.agent.prompts._prompts",
    # ── domain ────────────────────────────────────────────────────────────
    "uacragent.domain.providers",
    "uacragent.domain.rate_tiers",
    "uacragent.domain.types",
    "uacragent.domain.errors",
    "uacragent.domain.models",                # ReviewPlan / SectionSpec pydantic models
    "uacragent.domain.doc_priorities",
    # ── infra ─────────────────────────────────────────────────────────────
    "uacragent.infra.persistence",
    "uacragent.infra.vectorstore",
    "uacragent.infra.settings",
    "uacragent.infra.llm",
    "uacragent.infra.auth",
    "uacragent.infra.loaders",                # document loader (PDF/DOCX/PPTX/txt…)
    "uacragent.infra.updater",                # auto-updater (GitHub Releases)
    "uacragent.infra.workspace",              # WorkspacePaths dataclass
    # ── export ────────────────────────────────────────────────────────────
    "uacragent.export.docx",
    "uacragent.export.pdf",
    "uacragent.export.markdown",              # imported by pipeline
    "uacragent.export._utils",                # safe_timestamp helper
    # ── stdlib extras ─────────────────────────────────────────────────────
    "readline",
    "sqlite3",
    "_sqlite3",
]

# ---------------------------------------------------------------------------
# 4. Analysis
# ---------------------------------------------------------------------------
a = Analysis(
    [str(HERE / "src" / "uacragent" / "__main__.py")],
    pathex=[str(HERE / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[
        str(HERE / "rthooks" / "rthook_tkdnd_mac.py"),
        str(HERE / "rthooks" / "rthook_tesseract.py"),
    ],
    excludes=[
        "pytest", "_pytest",
        "fastapi", "uvicorn", "starlette",
        "IPython", "jupyter", "notebook",
        "matplotlib", "scipy", "sklearn",
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ---------------------------------------------------------------------------
# 5. Executable
# ---------------------------------------------------------------------------
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="UACRAgent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX can corrupt native extensions — keep off
    console=False,      # no terminal window on launch
    icon=str(HERE / "src" / "uacragent" / "assets" / "UACRAgent.icns"),
)

# ---------------------------------------------------------------------------
# 6. Bundle all into a single directory
# ---------------------------------------------------------------------------
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="UACRAgent",
)

# ---------------------------------------------------------------------------
# 7. macOS .app bundle
# ---------------------------------------------------------------------------
app = BUNDLE(
    coll,
    name="UACRAgent.app",
    icon=str(HERE / "src" / "uacragent" / "assets" / "UACRAgent.icns"),
    bundle_identifier="com.uacragent.app",
    info_plist={
        "CFBundleDisplayName":        "UACRAgent",
        "CFBundleName":               "UACRAgent",
        "CFBundleShortVersionString": _APP_VERSION,
        "CFBundleVersion":            _APP_VERSION,
        "NSHighResolutionCapable":    True,
        "NSHumanReadableCopyright":   "Copyright © 2026 Lizhuo Xu. MIT License.",
        "LSMinimumSystemVersion":     "12.0",
        "LSUIElement":                False,
    },
)

# ---------------------------------------------------------------------------
# 8. Post-bundle: re-sign the tkdnd dylib with a plain ad-hoc signature
# ---------------------------------------------------------------------------
# Root cause of "Unable to load tkdnd library." on Apple Silicon macOS:
#
# The tkdnd dylib from the tkinterdnd2 wheel carries CS_LINKER_SIGNED
# (flags=0x20002, adhoc|linker-signed).  macOS enforces that a dylib loaded
# via dlopen() inside a signed app context must be signed with a compatible
# signature.  A linker-signed dylib is treated as a separate signing context
# and is rejected when the calling process was signed by codesign (even
# ad-hoc).
#
# Files placed in `binaries` are re-signed by PyInstaller's binary pipeline,
# removing CS_LINKER_SIGNED.  Files placed in `datas` are copied verbatim,
# preserving the incompatible flag.  We use `datas` for the dylib to
# guarantee exact placement at the path pkgIndex.tcl expects; we then fix
# the signature here with a post-bundle codesign pass.
#
# Step 1 — re-sign the tkdnd dylib (replaces linker-signed with plain adhoc).
# Step 2 — re-sign the entire .app bundle so the outer signature covers the
#           newly signed dylib (modifying a bundle component invalidates the
#           outer signature if one exists).
import subprocess as _cs_sp, glob as _cs_gl

_bundle_app   = str(HERE / "dist" / "UACRAgent.app")
_dylib_glob   = str(
    HERE / "dist" / "UACRAgent.app" / "Contents" / "Frameworks" /
    "tkinterdnd2" / "tkdnd" / _tkdnd_subdir / "*.dylib"
)

print("INFO: re-signing tkdnd dylib(s) to remove CS_LINKER_SIGNED …")
_signed_any = False
for _dl in _cs_gl.glob(_dylib_glob):
    _r = _cs_sp.run(
        ["codesign", "--force", "--sign", "-", _dl],
        capture_output=True, text=True,
    )
    if _r.returncode == 0:
        print(f"  ✓ signed {_dl}")
        _signed_any = True
    else:
        print(f"  ✗ codesign failed for {_dl}: {_r.stderr.strip()}")

if not _signed_any:
    print(
        "WARNING: no tkdnd dylib found to sign — "
        f"drag-and-drop may not work. Pattern was: {_dylib_glob}"
    )

print("INFO: re-signing UACRAgent.app bundle …")
_r = _cs_sp.run(
    ["codesign", "--force", "--deep", "--sign", "-", _bundle_app],
    capture_output=True, text=True,
)
if _r.returncode == 0:
    print("  ✓ bundle re-signed.")
else:
    print(f"  ✗ bundle re-sign failed: {_r.stderr.strip()}")

del _cs_sp, _cs_gl, _bundle_app, _dylib_glob
