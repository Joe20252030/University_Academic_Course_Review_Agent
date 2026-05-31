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

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_all

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

# tkinterdnd2 — include the entire package dir so Tcl can find tkdnd
import tkinterdnd2 as _tkdnd
datas += [(str(Path(_tkdnd.__file__).parent), "tkinterdnd2")]

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
    "uacragent.infra.loaders",                # document loader (PDF/DOCX/txt…)
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
    runtime_hooks=[str(HERE / "rthooks" / "rthook_tkdnd.py")],
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
