"""UACRAgent desktop GUI — pure tkinter, cross-platform (macOS + Windows).

Launch:
    python -m uacragent.ui.desktop.app
or:
    from uacragent.ui.desktop.app import main; main()
"""
from __future__ import annotations

import os
import platform
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from uacragent.agent.service import AgentService, ReviewResult
from uacragent.domain.errors import UACRAgentError
from uacragent.domain.types import ExamFormat, ExportFormat
from uacragent.export.docx import save_docx
from uacragent.export.pdf import save_pdf
from uacragent.infra.workspace import workspace_paths, ensure_workspace_dirs


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_WINDOW_TITLE = "UACRAgent - Course Review Generator"
_MIN_WIDTH = 720
_MIN_HEIGHT = 560
_PAD = 10
_SUPPORTED_FILETYPES = [
    ("All supported", "*.pdf *.txt *.md"),
    ("PDF files", "*.pdf"),
    ("Text files", "*.txt"),
    ("Markdown files", "*.md"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _open_file_in_os(path: str) -> None:
    """Open a file with the default system application (works on macOS + Windows)."""
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.Popen(["open", path])
        elif system == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


def _open_folder_in_os(path: str) -> None:
    """Open a folder in the system file manager."""
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.Popen(["open", path])
        elif system == "Windows":
            subprocess.Popen(["explorer", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class UACRAgentApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(_WINDOW_TITLE)
        self.minsize(_MIN_WIDTH, _MIN_HEIGHT)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        # State
        self._selected_files: list[str] = []
        self._result: ReviewResult | None = None
        self._last_output_path: str = ""
        self._is_running = False

        self._build_ui()

    # ----- UI construction ------------------------------------------------

    def _build_ui(self) -> None:
        main_frame = ttk.Frame(self, padding=_PAD)
        main_frame.grid(row=0, column=0, sticky="nsew")
        main_frame.columnconfigure(0, weight=1)

        row = 0

        # ── Title ─────────────────────────────────────────────
        title_lbl = ttk.Label(
            main_frame, text="Course Review Generator", font=("TkDefaultFont", 16, "bold")
        )
        title_lbl.grid(row=row, column=0, sticky="w", pady=(0, _PAD))
        row += 1

        # ── File selection ────────────────────────────────────
        file_frame = ttk.LabelFrame(main_frame, text="Course Materials", padding=_PAD)
        file_frame.grid(row=row, column=0, sticky="ew", pady=(0, _PAD))
        file_frame.columnconfigure(0, weight=1)

        self._file_listbox = tk.Listbox(file_frame, height=4, selectmode=tk.EXTENDED)
        self._file_listbox.grid(row=0, column=0, sticky="ew", padx=(0, _PAD))

        btn_frame = ttk.Frame(file_frame)
        btn_frame.grid(row=0, column=1, sticky="ns")

        ttk.Button(btn_frame, text="Add Files...", command=self._on_add_files).pack(fill="x", pady=(0, 4))
        ttk.Button(btn_frame, text="Remove Selected", command=self._on_remove_files).pack(fill="x")
        row += 1

        # ── Options ───────────────────────────────────────────
        opts_frame = ttk.LabelFrame(main_frame, text="Options", padding=_PAD)
        opts_frame.grid(row=row, column=0, sticky="ew", pady=(0, _PAD))

        # Exam format
        ttk.Label(opts_frame, text="Exam format:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self._exam_format_var = tk.StringVar(value=ExamFormat.written.value)
        exam_cb = ttk.Combobox(
            opts_frame,
            textvariable=self._exam_format_var,
            values=[e.value for e in ExamFormat],
            state="readonly",
            width=14,
        )
        exam_cb.grid(row=0, column=1, sticky="w", padx=(0, 20))

        # Export format
        ttk.Label(opts_frame, text="Export format:").grid(row=0, column=2, sticky="w", padx=(0, 6))
        self._export_format_var = tk.StringVar(value=ExportFormat.markdown.value)
        export_cb = ttk.Combobox(
            opts_frame,
            textvariable=self._export_format_var,
            values=[e.value for e in ExportFormat],
            state="readonly",
            width=14,
        )
        export_cb.grid(row=0, column=3, sticky="w", padx=(0, 20))

        # Workspace ID
        ttk.Label(opts_frame, text="Workspace:").grid(row=0, column=4, sticky="w", padx=(0, 6))
        self._workspace_var = tk.StringVar(value="default")
        ttk.Entry(opts_frame, textvariable=self._workspace_var, width=14).grid(row=0, column=5, sticky="w")
        row += 1

        # ── Generate button ───────────────────────────────────
        self._generate_btn = ttk.Button(
            main_frame, text="Generate Review", command=self._on_generate
        )
        self._generate_btn.grid(row=row, column=0, pady=(0, _PAD))
        row += 1

        # ── Progress ──────────────────────────────────────────
        self._progress = ttk.Progressbar(main_frame, mode="indeterminate")
        self._progress.grid(row=row, column=0, sticky="ew", pady=(0, 4))
        row += 1

        self._status_var = tk.StringVar(value="Ready. Add course materials and click Generate.")
        ttk.Label(main_frame, textvariable=self._status_var).grid(row=row, column=0, sticky="w", pady=(0, _PAD))
        row += 1

        # ── Output area ───────────────────────────────────────
        output_frame = ttk.LabelFrame(main_frame, text="Output Preview", padding=_PAD)
        output_frame.grid(row=row, column=0, sticky="nsew", pady=(0, _PAD))
        output_frame.columnconfigure(0, weight=1)
        output_frame.rowconfigure(0, weight=1)
        main_frame.rowconfigure(row, weight=1)

        self._output_text = tk.Text(output_frame, wrap="word", state="disabled", height=10)
        scrollbar = ttk.Scrollbar(output_frame, orient="vertical", command=self._output_text.yview)
        self._output_text.configure(yscrollcommand=scrollbar.set)
        self._output_text.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        row += 1

        # ── Bottom buttons ────────────────────────────────────
        bottom = ttk.Frame(main_frame)
        bottom.grid(row=row, column=0, sticky="e")

        self._open_file_btn = ttk.Button(bottom, text="Open Output File", command=self._on_open_file, state="disabled")
        self._open_file_btn.pack(side="left", padx=(0, 6))

        self._open_folder_btn = ttk.Button(bottom, text="Open Output Folder", command=self._on_open_folder, state="disabled")
        self._open_folder_btn.pack(side="left")

    # ----- Callbacks ------------------------------------------------------

    def _on_add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Select course material files",
            filetypes=_SUPPORTED_FILETYPES,
        )
        for p in paths:
            if p not in self._selected_files:
                self._selected_files.append(p)
                self._file_listbox.insert(tk.END, p)

    def _on_remove_files(self) -> None:
        indices = list(self._file_listbox.curselection())
        for i in reversed(indices):
            self._file_listbox.delete(i)
            self._selected_files.pop(i)

    def _on_generate(self) -> None:
        if self._is_running:
            return
        if not self._selected_files:
            messagebox.showwarning("No files", "Please add at least one course material file.")
            return

        self._is_running = True
        self._generate_btn.configure(state="disabled")
        self._open_file_btn.configure(state="disabled")
        self._open_folder_btn.configure(state="disabled")
        self._progress.start(15)
        self._status_var.set("Generating review... This may take a minute.")
        self._set_output_text("")

        # Run the pipeline in a background thread to keep the UI responsive.
        thread = threading.Thread(target=self._run_pipeline, daemon=True)
        thread.start()

    def _run_pipeline(self) -> None:
        try:
            service = AgentService()
            exam_format = self._exam_format_var.get()
            workspace_id = self._workspace_var.get() or "default"
            export_fmt = self._export_format_var.get()

            result = service.run_end_to_end(
                file_paths=list(self._selected_files),
                exam_format=exam_format,
                workspace_id=workspace_id,
            )

            # Export to the chosen format
            ws = workspace_paths(service.settings.workspace_root, workspace_id)
            ensure_workspace_dirs(ws)

            if export_fmt == ExportFormat.docx.value:
                output_path = save_docx(result.markdown, ws)
            elif export_fmt == ExportFormat.pdf.value:
                output_path = save_pdf(result.markdown, ws)
            else:
                output_path = result.markdown_path  # already saved as .md

            self._result = result
            self._last_output_path = output_path

            # Schedule UI update on main thread
            self.after(0, self._on_pipeline_success, result, output_path)

        except UACRAgentError as exc:
            self.after(0, self._on_pipeline_error, str(exc))
        except Exception as exc:
            self.after(0, self._on_pipeline_error, f"Unexpected error: {exc}")

    def _on_pipeline_success(self, result: ReviewResult, output_path: str) -> None:
        self._progress.stop()
        self._is_running = False
        self._generate_btn.configure(state="normal")
        self._open_file_btn.configure(state="normal")
        self._open_folder_btn.configure(state="normal")
        self._status_var.set(f"Done! Output saved to: {output_path}")

        # Show a preview of the markdown
        preview = result.markdown
        if len(preview) > 5000:
            preview = preview[:5000] + "\n\n... (truncated preview) ..."
        self._set_output_text(preview)

    def _on_pipeline_error(self, error_msg: str) -> None:
        self._progress.stop()
        self._is_running = False
        self._generate_btn.configure(state="normal")
        self._status_var.set(f"Error: {error_msg}")
        messagebox.showerror("Generation Failed", error_msg)

    def _on_open_file(self) -> None:
        if self._last_output_path and Path(self._last_output_path).exists():
            _open_file_in_os(self._last_output_path)

    def _on_open_folder(self) -> None:
        if self._last_output_path:
            folder = str(Path(self._last_output_path).parent)
            _open_folder_in_os(folder)

    # ----- Utilities ------------------------------------------------------

    def _set_output_text(self, text: str) -> None:
        self._output_text.configure(state="normal")
        self._output_text.delete("1.0", tk.END)
        self._output_text.insert("1.0", text)
        self._output_text.configure(state="disabled")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()

    app = UACRAgentApp()
    app.mainloop()


if __name__ == "__main__":
    main()
