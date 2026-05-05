"""UACRAgent desktop GUI — pure tkinter, cross-platform (macOS + Windows + Linux).

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
from uacragent.domain.types import DocumentType, ExamFormat, ExamType, ExportFormat, TaskType
from uacragent.export.docx import save_docx
from uacragent.export.pdf import save_pdf
from uacragent.infra.workspace import workspace_paths, ensure_workspace_dirs


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_WINDOW_TITLE = "UACRAgent - Course Review Generator"
_MIN_WIDTH = 960
_MIN_HEIGHT = 880
_PAD = 10
_SUPPORTED_FILETYPES = [
    ("All supported", "*.pdf *.txt *.md *.docx"),
    ("PDF files", "*.pdf"),
    ("Word documents", "*.docx"),
    ("Text files", "*.txt"),
    ("Markdown files", "*.md"),
]

_DOC_TYPE_LABELS = {
    DocumentType.syllabus: "Syllabus",
    DocumentType.lecture_note: "Lecture Notes",
    DocumentType.textbook: "Textbook",
    DocumentType.assignment: "Assignments",
    DocumentType.past_exam: "Past Exams",
    DocumentType.other: "Other",
}

_EXAM_TYPE_LABELS = {
    ExamType.quiz: "Quiz",
    ExamType.midterm: "Midterm",
    ExamType.final: "Final Exam",
    ExamType.term_test: "Term Test",
    ExamType.other: "Other",
}

_TASK_TYPE_LABELS = {
    TaskType.review_summary: "Review Summary",
    TaskType.practice_booklet: "Practice Booklet",
    TaskType.mock_exam: "Mock Exam",
    TaskType.exam_prediction: "Exam Prediction",
}

_TASK_HINTS: dict[TaskType, str] = {
    TaskType.review_summary: (
        'Optional: e.g. "Focus on chapters 5-8" or "Emphasize calculation problems"'
    ),
    TaskType.practice_booklet: (
        'Optional: e.g. "Include 10 problems per section" or "Focus on problem-solving skills"'
    ),
    TaskType.mock_exam: (
        'Optional: e.g. "2 hours, 100 points total" or "Include a formula sheet section"'
    ),
    TaskType.exam_prediction: (
        'Optional: e.g. "Professor emphasized graph theory" or "Last year\'s final focused on chapters 3-6"'
    ),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _open_file_in_os(path: str) -> None:
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

        self._classified_files: dict[DocumentType, list[str]] = {
            doc_type: [] for doc_type in DocumentType
        }
        self._result: ReviewResult | None = None
        self._last_output_path: str = ""
        self._is_running = False
        self._service: AgentService | None = None  # lazy, cached

        self._file_listboxes: dict[DocumentType, tk.Listbox] = {}

        self._build_ui()

    # ----- Service (cached) -----------------------------------------------

    def _get_service(self) -> AgentService:
        if self._service is None:
            self._service = AgentService()
        return self._service

    # ----- UI construction ------------------------------------------------

    def _build_ui(self) -> None:
        main_frame = ttk.Frame(self, padding=_PAD)
        main_frame.grid(row=0, column=0, sticky="nsew")
        main_frame.columnconfigure(0, weight=1)

        row = 0

        # -- Title ---------------------------------------------------------
        ttk.Label(
            main_frame, text="Course Review Generator", font=("TkDefaultFont", 16, "bold")
        ).grid(row=row, column=0, sticky="w", pady=(0, _PAD))
        row += 1

        # -- Course Information --------------------------------------------
        info_frame = ttk.LabelFrame(main_frame, text="Course Information", padding=_PAD)
        info_frame.grid(row=row, column=0, sticky="ew", pady=(0, _PAD))
        info_frame.columnconfigure(1, weight=2)
        info_frame.columnconfigure(3, weight=1)
        info_frame.columnconfigure(5, weight=1)

        # Row 0: Course Name (required, spans full width)
        ttk.Label(info_frame, text="Course Name *:", foreground="red").grid(
            row=0, column=0, sticky="w", padx=(0, 4)
        )
        self._course_name_var = tk.StringVar()
        self._course_name_entry = ttk.Entry(info_frame, textvariable=self._course_name_var)
        self._course_name_entry.grid(row=0, column=1, columnspan=5, sticky="ew")

        # Row 1: University | Major | Semester
        ttk.Label(info_frame, text="University:").grid(row=1, column=0, sticky="w", padx=(0, 4), pady=(6, 0))
        self._university_var = tk.StringVar()
        ttk.Entry(info_frame, textvariable=self._university_var).grid(
            row=1, column=1, sticky="ew", padx=(0, 12), pady=(6, 0)
        )

        ttk.Label(info_frame, text="Major / Dept:").grid(row=1, column=2, sticky="w", padx=(0, 4), pady=(6, 0))
        self._major_var = tk.StringVar()
        ttk.Entry(info_frame, textvariable=self._major_var).grid(
            row=1, column=3, sticky="ew", padx=(0, 12), pady=(6, 0)
        )

        ttk.Label(info_frame, text="Semester:").grid(row=1, column=4, sticky="w", padx=(0, 4), pady=(6, 0))
        self._semester_var = tk.StringVar()
        ttk.Entry(info_frame, textvariable=self._semester_var).grid(
            row=1, column=5, sticky="ew", pady=(6, 0)
        )

        # Row 2: Course Code | Professor
        ttk.Label(info_frame, text="Course Code:").grid(row=2, column=0, sticky="w", padx=(0, 4), pady=(6, 0))
        self._course_code_var = tk.StringVar()
        ttk.Entry(info_frame, textvariable=self._course_code_var).grid(
            row=2, column=1, sticky="ew", padx=(0, 12), pady=(6, 0)
        )

        ttk.Label(info_frame, text="Professor:").grid(row=2, column=2, sticky="w", padx=(0, 4), pady=(6, 0))
        self._professor_var = tk.StringVar()
        ttk.Entry(info_frame, textvariable=self._professor_var).grid(
            row=2, column=3, columnspan=3, sticky="ew", pady=(6, 0)
        )

        row += 1

        # -- Document Type Sections ----------------------------------------
        docs_frame = ttk.LabelFrame(main_frame, text="Course Materials (by type)", padding=_PAD)
        docs_frame.grid(row=row, column=0, sticky="nsew", pady=(0, _PAD))
        docs_frame.columnconfigure(0, weight=1)
        docs_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(row, weight=1)

        doc_types = list(DocumentType)
        for i, doc_type in enumerate(doc_types):
            col = i % 2
            section_row = i // 2
            self._create_doc_type_section(docs_frame, doc_type, section_row, col)

        row += 1

        # -- Task selection ------------------------------------------------
        task_frame = ttk.LabelFrame(main_frame, text="Task", padding=_PAD)
        task_frame.grid(row=row, column=0, sticky="ew", pady=(0, _PAD))
        task_frame.columnconfigure(1, weight=1)

        ttk.Label(task_frame, text="What to generate:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self._task_type_var = tk.StringVar(value=TaskType.review_summary.value)
        task_cb = ttk.Combobox(
            task_frame,
            textvariable=self._task_type_var,
            values=[t.value for t in TaskType],
            state="readonly",
            width=20,
        )
        task_cb.grid(row=0, column=1, sticky="w", padx=(0, 20))
        task_cb.bind("<<ComboboxSelected>>", self._on_task_type_changed)

        self._task_desc_var = tk.StringVar(
            value="Generate a comprehensive review summary for exam preparation."
        )
        ttk.Label(task_frame, textvariable=self._task_desc_var, foreground="gray").grid(
            row=0, column=2, sticky="w"
        )

        ttk.Label(task_frame, text="Extra instructions:").grid(
            row=1, column=0, sticky="nw", padx=(0, 6), pady=(6, 0)
        )
        self._extra_instructions_text = tk.Text(task_frame, height=2, width=60, wrap="word")
        self._extra_instructions_text.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(6, 0))
        self._extra_instructions_text.bind("<FocusIn>", self._on_extra_focus_in)
        self._extra_instructions_text.bind("<FocusOut>", self._on_extra_focus_out)
        self._set_extra_hint()

        row += 1

        # -- Exam & Export Options -----------------------------------------
        opts_frame = ttk.LabelFrame(main_frame, text="Exam & Export Options", padding=_PAD)
        opts_frame.grid(row=row, column=0, sticky="ew", pady=(0, _PAD))

        ttk.Label(opts_frame, text="Exam type:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self._exam_type_var = tk.StringVar(value=ExamType.final.value)
        ttk.Combobox(
            opts_frame,
            textvariable=self._exam_type_var,
            values=[e.value for e in ExamType],
            state="readonly",
            width=12,
        ).grid(row=0, column=1, sticky="w", padx=(0, 20))

        ttk.Label(opts_frame, text="Exam format:").grid(row=0, column=2, sticky="w", padx=(0, 6))
        self._exam_format_var = tk.StringVar(value=ExamFormat.written.value)
        ttk.Combobox(
            opts_frame,
            textvariable=self._exam_format_var,
            values=[e.value for e in ExamFormat],
            state="readonly",
            width=12,
        ).grid(row=0, column=3, sticky="w", padx=(0, 20))

        ttk.Label(opts_frame, text="Export format:").grid(row=0, column=4, sticky="w", padx=(0, 6))
        self._export_format_var = tk.StringVar(value=ExportFormat.markdown.value)
        ttk.Combobox(
            opts_frame,
            textvariable=self._export_format_var,
            values=[e.value for e in ExportFormat],
            state="readonly",
            width=12,
        ).grid(row=0, column=5, sticky="w", padx=(0, 20))

        ttk.Label(opts_frame, text="Workspace:").grid(row=0, column=6, sticky="w", padx=(0, 6))
        self._workspace_var = tk.StringVar(value="default")
        ttk.Entry(opts_frame, textvariable=self._workspace_var, width=12).grid(row=0, column=7, sticky="w")
        row += 1

        # -- Generate button -----------------------------------------------
        self._generate_btn = ttk.Button(
            main_frame, text="Generate", command=self._on_generate
        )
        self._generate_btn.grid(row=row, column=0, pady=(0, _PAD))
        row += 1

        # -- Progress ------------------------------------------------------
        self._progress = ttk.Progressbar(main_frame, mode="indeterminate")
        self._progress.grid(row=row, column=0, sticky="ew", pady=(0, 4))
        row += 1

        self._status_var = tk.StringVar(
            value="Ready. Add course materials, choose a task, and click Generate."
        )
        ttk.Label(main_frame, textvariable=self._status_var).grid(
            row=row, column=0, sticky="w", pady=(0, _PAD)
        )
        row += 1

        # -- Output area ---------------------------------------------------
        output_frame = ttk.LabelFrame(main_frame, text="Output Preview", padding=_PAD)
        output_frame.grid(row=row, column=0, sticky="nsew", pady=(0, _PAD))
        output_frame.columnconfigure(0, weight=1)
        output_frame.rowconfigure(0, weight=1)

        self._output_text = tk.Text(output_frame, wrap="word", state="disabled", height=8)
        scrollbar = ttk.Scrollbar(output_frame, orient="vertical", command=self._output_text.yview)
        self._output_text.configure(yscrollcommand=scrollbar.set)
        self._output_text.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        row += 1

        # -- Bottom buttons ------------------------------------------------
        bottom = ttk.Frame(main_frame)
        bottom.grid(row=row, column=0, sticky="e")

        self._open_file_btn = ttk.Button(
            bottom, text="Open Output File", command=self._on_open_file, state="disabled"
        )
        self._open_file_btn.pack(side="left", padx=(0, 6))

        self._open_folder_btn = ttk.Button(
            bottom, text="Open Output Folder", command=self._on_open_folder, state="disabled"
        )
        self._open_folder_btn.pack(side="left")

    def _create_doc_type_section(
        self,
        parent: ttk.Frame,
        doc_type: DocumentType,
        row: int,
        col: int,
    ) -> None:
        label = _DOC_TYPE_LABELS.get(doc_type, doc_type.value)

        frame = ttk.LabelFrame(parent, text=label, padding=5)
        frame.grid(row=row, column=col, sticky="nsew", padx=5, pady=5)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        parent.rowconfigure(row, weight=1)

        listbox = tk.Listbox(frame, height=3, selectmode=tk.EXTENDED)
        listbox.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self._file_listboxes[doc_type] = listbox

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=0, column=1, sticky="ns")

        ttk.Button(
            btn_frame, text="Add...", width=8,
            command=lambda dt=doc_type: self._on_add_files(dt)
        ).pack(fill="x", pady=(0, 2))
        ttk.Button(
            btn_frame, text="Remove", width=8,
            command=lambda dt=doc_type: self._on_remove_files(dt)
        ).pack(fill="x")

    # ----- Extra-instructions placeholder logic ---------------------------

    def _current_hint(self) -> str:
        try:
            tt = TaskType(self._task_type_var.get())
        except ValueError:
            tt = TaskType.review_summary
        return _TASK_HINTS.get(tt, "")

    def _set_extra_hint(self) -> None:
        """Replace the extra-instructions box content with the current hint."""
        self._extra_instructions_text.configure(foreground="gray")
        self._extra_instructions_text.delete("1.0", tk.END)
        self._extra_instructions_text.insert("1.0", self._current_hint())

    def _is_showing_hint(self) -> bool:
        current = self._extra_instructions_text.get("1.0", tk.END).strip()
        return current in _TASK_HINTS.values()

    def _on_extra_focus_in(self, _event: object = None) -> None:
        if self._is_showing_hint():
            self._extra_instructions_text.delete("1.0", tk.END)
            self._extra_instructions_text.configure(foreground="black")

    def _on_extra_focus_out(self, _event: object = None) -> None:
        current = self._extra_instructions_text.get("1.0", tk.END).strip()
        if not current:
            self._set_extra_hint()

    def _get_extra_instructions(self) -> str:
        text = self._extra_instructions_text.get("1.0", tk.END).strip()
        if self._is_showing_hint():
            return ""
        return text

    # ----- Task type UI helpers -------------------------------------------

    _TASK_DESCRIPTIONS: dict[str, str] = {
        TaskType.review_summary.value: "Generate a comprehensive review summary for exam preparation.",
        TaskType.practice_booklet.value: "Generate a booklet of practice problems organized by topic.",
        TaskType.mock_exam.value: "Generate a realistic mock exam with answer key.",
        TaskType.exam_prediction.value: "Predict likely exam topics and question types.",
    }

    def _on_task_type_changed(self, _event: object = None) -> None:
        task = self._task_type_var.get()
        self._task_desc_var.set(self._TASK_DESCRIPTIONS.get(task, ""))
        # Always replace the hint so it reflects the newly selected task
        if self._is_showing_hint():
            self._set_extra_hint()

    # ----- File management callbacks --------------------------------------

    def _on_add_files(self, doc_type: DocumentType) -> None:
        paths = filedialog.askopenfilenames(
            title=f"Select {_DOC_TYPE_LABELS.get(doc_type, doc_type.value)} files",
            filetypes=_SUPPORTED_FILETYPES,
        )
        listbox = self._file_listboxes[doc_type]
        for p in paths:
            if p not in self._classified_files[doc_type]:
                self._classified_files[doc_type].append(p)
                listbox.insert(tk.END, Path(p).name)

    def _on_remove_files(self, doc_type: DocumentType) -> None:
        listbox = self._file_listboxes[doc_type]
        indices = list(listbox.curselection())
        for i in reversed(indices):
            listbox.delete(i)
            self._classified_files[doc_type].pop(i)

    def _get_total_file_count(self) -> int:
        return sum(len(files) for files in self._classified_files.values())

    # ----- Generation -----------------------------------------------------

    def _on_generate(self) -> None:
        if self._is_running:
            return
        if not self._course_name_var.get().strip():
            messagebox.showwarning("Course Name Required", "Please enter a course name before generating.")
            self._course_name_entry.focus_set()
            return
        if self._get_total_file_count() == 0:
            messagebox.showwarning("No files", "Please add at least one course material file.")
            return

        self._is_running = True
        self._generate_btn.configure(state="disabled")
        self._open_file_btn.configure(state="disabled")
        self._open_folder_btn.configure(state="disabled")
        self._progress.start(15)
        task_label = _TASK_TYPE_LABELS.get(TaskType(self._task_type_var.get()), "output")
        self._status_var.set(f"Generating {task_label.lower()}... This may take a minute.")
        self._set_output_text("")

        thread = threading.Thread(target=self._run_pipeline, daemon=True)
        thread.start()

    def _run_pipeline(self) -> None:
        try:
            service = self._get_service()
            classified = {
                dt: paths for dt, paths in self._classified_files.items() if paths
            }

            result = service.run_end_to_end(
                classified_files=classified,
                exam_format=self._exam_format_var.get(),
                course_name=self._course_name_var.get().strip(),
                exam_type=self._exam_type_var.get(),
                task_type=self._task_type_var.get(),
                extra_instructions=self._get_extra_instructions(),
                workspace_id=self._workspace_var.get() or "default",
                copy_to_workspace=True,
                university_name=self._university_var.get().strip(),
                major=self._major_var.get().strip(),
                course_code=self._course_code_var.get().strip(),
                professor_name=self._professor_var.get().strip(),
                semester=self._semester_var.get().strip(),
            )

            ws = workspace_paths(service.settings.workspace_root, self._workspace_var.get() or "default")
            ensure_workspace_dirs(ws)

            export_fmt = self._export_format_var.get()
            if export_fmt == ExportFormat.docx.value:
                output_path = save_docx(result.markdown, ws)
            elif export_fmt == ExportFormat.pdf.value:
                output_path = save_pdf(result.markdown, ws)
            else:
                output_path = result.markdown_path

            self._result = result
            self._last_output_path = output_path

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
            _open_folder_in_os(str(Path(self._last_output_path).parent))

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
