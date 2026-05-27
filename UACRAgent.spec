# UACRAgent.spec  — PyInstaller build spec for macOS
# Run with:  pyinstaller UACRAgent.spec
# ---------------------------------------------------------------------------
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_all

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
]:
    d, b, h = collect_all(pkg)
    datas         += d
    binaries      += b
    hiddenimports += h

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
    runtime_hooks=[],
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
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion":            "0.1.0",
        "NSHighResolutionCapable":    True,
        "NSHumanReadableCopyright":   "MIT License",
        "LSMinimumSystemVersion":     "12.0",
        "LSUIElement":                False,
    },
)
