# UACRAgent_win.spec  — PyInstaller build spec for Windows
# Run with:  pyinstaller UACRAgent_win.spec
# ---------------------------------------------------------------------------
import sys
from pathlib import Path

# Read the canonical version from pyproject.toml so the .exe always
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
# 0. Generate Windows version-info file dynamically from pyproject.toml
#    This populates the Properties → Details tab of the .exe on Windows.
# ---------------------------------------------------------------------------
_ver_parts = [int(x) for x in _APP_VERSION.split(".")[:3]] + [0]
_ver_tuple = tuple(_ver_parts)                            # e.g. (0, 1, 2, 0)
_ver_str   = ".".join(str(x) for x in _ver_parts)        # e.g. "0.1.2.0"

_version_info_content = f"""\
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={_ver_tuple},
    prodvers={_ver_tuple},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0),
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName',      'Lizhuo Xu'),
          StringStruct('FileDescription',  'University Academic Course Review Agent'),
          StringStruct('FileVersion',      '{_ver_str}'),
          StringStruct('InternalName',     'UACRAgent'),
          StringStruct('LegalCopyright',   'Copyright (c) 2026 Lizhuo Xu. MIT License.'),
          StringStruct('OriginalFilename', 'UACRAgent.exe'),
          StringStruct('ProductName',      'UACRAgent'),
          StringStruct('ProductVersion',   '{_ver_str}'),
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [0x0409, 1200])])
  ]
)
"""
_version_file = str(HERE / "_win_version_info.txt")
with open(_version_file, "w", encoding="utf-8") as _vf:
    _vf.write(_version_info_content)

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
    # Local embedding in the frozen .exe uses Chroma's built-in ONNX path for
    # all-MiniLM-L6-v2. The broader sentence-transformers model list remains
    # source-mode only because PyTorch is not reliable enough in the packaged app.
    "onnxruntime",    # primary local-embedding runtime in frozen .exe
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

# certifi — CA bundle used by updater.py for HTTPS requests.
# Windows frozen apps use SChannel (Windows cert store) and don't need this to
# function, but bundling it explicitly ensures _make_ssl_context() can load
# certifi.where() without falling back, and keeps the two specs symmetric.
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
# Default Tesseract installation paths on Windows:
#   Installer (GitHub releases) : C:\Program Files\Tesseract-OCR\tesseract.exe
#                                  C:\Program Files\Tesseract-OCR\tessdata\
#
# rthook_tesseract.py configures TESSDATA_PREFIX and pytesseract.tesseract_cmd
# at runtime so application code never needs to know the bundled path.

import shutil as _shutil
import os as _os

_tess_bin = (
    _shutil.which("tesseract")
    or r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)
_tess_bin_path = Path(_tess_bin) if _tess_bin and Path(_tess_bin).is_file() else None

if _tess_bin_path:
    binaries += [(str(_tess_bin_path), ".")]
    # Tessdata lives next to the binary in Tesseract-OCR installation.
    _possible_tessdata = [
        _tess_bin_path.parent / "tessdata",
        Path(r"C:\Program Files\Tesseract-OCR\tessdata"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tessdata"),
    ]
    _tessdata_dir = next(
        (p for p in _possible_tessdata if (p / "eng.traineddata").is_file()),
        None,
    )
    if _tessdata_dir:
        _eng_data = _tessdata_dir / "eng.traineddata"
        datas += [(str(_eng_data), "tessdata")]
        print(f"INFO: Bundling Tesseract from {_tess_bin_path}, tessdata from {_tessdata_dir}")
    else:
        print("WARNING: eng.traineddata not found — OCR will be unavailable in the built app.")
else:
    print("WARNING: tesseract.exe not found. Download from https://github.com/UB-Mannheim/tesseract/wiki")
    print("         OCR on PPTX image slides will be unavailable in the built app.")

# tkinterdnd2 — bundle the platform-specific tkdnd extension correctly.
#
# Both the DLL AND the .tcl scripts go into datas, not binaries.
# See UACRAgent_mac.spec for the full rationale; the short version:
#   PyInstaller's binary pipeline may relocate a DLL whose install name is a
#   bare filename to _MEIPASS root, while pkgIndex.tcl still refers to the
#   platform subdirectory.  Tcl's `load $dir/$lib` then fails even though the
#   file exists — it just isn't where Tcl looks.  Putting the DLL in datas
#   guarantees exact placement at _MEIPASS/tkinterdnd2/tkdnd/<arch>/<dll>.
#
# DLL dependency resolution for Tcl's LoadLibrary is handled separately by
# the TCLLIBPATH + PATH prepend in rthook_tkdnd.py.
import platform as _plat
import os as _os
import tkinterdnd2 as _tkdnd

_tkdnd_pkg_dir  = Path(_tkdnd.__file__).parent
# On Windows platform.machine() may return the HOST arch; PROCESSOR_ARCHITECTURE
# is set by WOW64 and reflects the running-process architecture.
_tkdnd_machine  = _os.environ.get("PROCESSOR_ARCHITECTURE", _plat.machine())
if _tkdnd_machine == "ARM64":
    _tkdnd_subdir = "win-arm64"
elif _tkdnd_machine in ("AMD64", "x86_64"):
    _tkdnd_subdir = "win-x64"
else:
    _tkdnd_subdir = "win-x86"

_tkdnd_plat_dir = _tkdnd_pkg_dir / "tkdnd" / _tkdnd_subdir

if _tkdnd_plat_dir.is_dir():
    _tkdnd_dest = f"tkinterdnd2/tkdnd/{_tkdnd_subdir}"
    # DLL → datas (exact placement guaranteed; avoids binary-pipeline relocation)
    for _f in _tkdnd_plat_dir.glob("*.dll"):
        datas += [(str(_f), _tkdnd_dest)]
    for _f in _tkdnd_plat_dir.glob("*.tcl"):
        datas += [(str(_f), _tkdnd_dest)]
else:
    print(f"WARNING: tkdnd platform dir not found: {_tkdnd_plat_dir}")

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
    # NOTE: 'readline' is Unix-only and intentionally omitted on Windows.
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
        str(HERE / "rthooks" / "rthook_tkdnd.py"),
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
    console=False,      # no console window (windowed / GUI app)
    icon=str(HERE / "src" / "uacragent" / "assets" / "logo.ico"),
    version=_version_file,  # Properties → Details tab metadata
)

# ---------------------------------------------------------------------------
# 6. Bundle all into a single directory
#    On Windows there is no BUNDLE step — the COLLECT output IS the release
#    artefact.  Zip the 'dist/UACRAgent' folder or wrap it in an NSIS / WiX
#    installer if a proper installer is desired.
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
