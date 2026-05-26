"""Module-level UI constants for the desktop application.

Contains display strings (_STRINGS), colour palettes (_THEME_COLORS),
font-size values, and OS-helper functions.  All other desktop modules
import from here instead of from app.py so there is a single source
of truth for every UI literal.
"""
from __future__ import annotations

import os
import platform
import re
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

from uacragent.domain.types import DocumentType

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_WINDOW_TITLE = "UACRAgent - Course Review Assistant"
_MIN_WIDTH  = 1000   # hard minimum — window cannot be shrunk below this
_MIN_HEIGHT = 620
_INIT_WIDTH  = 1280  # default size on first launch (larger for comfortable layout)
_INIT_HEIGHT = 800
_PAD = 8
_SESSION_LIST_WIDTH = 220

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
# (label_i18n_key, message_sent_to_llm)
_QUICK_ACTIONS = [
    ("review_summary",    "Generate a review summary for this course."),
    ("practice_booklet",  "Generate a practice booklet for this course."),
    ("mock_exam",         "Generate a mock exam for this course."),
    ("exam_prediction",   "Generate an exam prediction for this course."),
]

# ---------------------------------------------------------------------------
# Internationalisation — UI display strings
# ---------------------------------------------------------------------------
_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # Session list
        "sessions":           "Sessions",
        "new_session":        "+ New Session",
        "app_settings":       "⚙  App Settings",
        "rename":             "✏  Rename",
        "delete":             "🗑  Delete",
        # Chat pane
        "settings_btn":       "⚙  Session Settings",
        "quick_actions":      "Quick Actions",
        "review_summary":     "Review Summary",
        "practice_booklet":   "Practice Booklet",
        "mock_exam":          "Mock Exam",
        "exam_prediction":    "Exam Prediction",
        "effort_label":       "Effort:",
        "low":                "Low",
        "medium":             "Medium",
        "high":               "High",
        # Reasoning mode chip (next to Effort)
        "reasoning_mode_label":  "Reasoning:",
        "quick":                 "Quick Review",
        "deep":                  "Deep Analysis",
        "reasoning_quick_desc":  "Faster generation with lower token usage.",
        "reasoning_deep_desc":   "More comprehensive reasoning with higher token usage.",
        "send":               "Send",
        "cancel":             "✕ Cancel",
        "placeholder":        "Select a session from the left panel\nor click  + New  to create a new one.",
        # App Settings dialog
        "app_settings_title": "App Settings",
        "appearance_section": "Appearance",
        "color_mode_label":   "Color mode:",
        "light_mode":         "Light",
        "dark_mode":          "Dark",
        "font_size_label":    "Font size:",
        "font_small":         "Small",
        "font_medium":        "Medium",
        "font_large":         "Large",
        "language_label":     "Language:",
        "app_data_label":     "App data folder:",
        "app_data_hint":      (
            "The index.json and any auto-created session workspaces\n"
            "are stored here.  Changes take effect on next launch."
        ),
        "save":               "Save",
        "cancel_btn":         "Cancel",
        # --- Session Settings dialog ---
        "settings_dialog_title":    "Session Settings",
        "settings_banner":          (
            "✏️  Edit any setting below, then scroll down and click  ✓ Apply  "
            "to save and re-index."
        ),
        "settings_model_section":   "Model",
        "settings_provider_label":  "Provider:",
        "settings_model_label":     "Model:",
        "settings_api_key_section": "API Key",
        "settings_show_key":        "Show",
        "settings_hide_key":        "Hide",
        "settings_api_key_note": (
            "ℹ️  API keys are shared across all sessions for the lifetime of this "
            "app window.\n"
            "A key entered here applies to every session until the app is closed "
            "or the key is changed.\n"
            "Keys are never saved to disk — re-enter them each time you open the "
            "app, or add them to a .env file."
        ),
        "settings_embedding_section":    "Embedding",
        "settings_course_section":       "Course Information",
        "settings_course_name_field":    "Course Name *",
        "settings_university_field":     "University",
        "settings_major_field":          "Major / Department",
        "settings_course_code_field":    "Course Code",
        "settings_professor_field":      "Professor",
        "settings_semester_field":       "Semester",
        "settings_exam_section":         "Exam Options",
        "settings_exam_type_label":      "Exam type:",
        "settings_exam_format_label":    "Exam format:",
        "settings_exam_duration_label":  "Exam duration:",
        "settings_exam_info_label":      "Exam info sheet:",
        "settings_browse_btn":           "Browse...",
        "settings_clear_btn":            "Clear",
        "settings_workspace_section":    "Workspace & Export",
        "settings_workspace_label":      "Workspace folder:",
        "settings_open_btn":             "Open",
        "settings_reset_btn":            "Reset",
        "settings_deletion_warning_title": "⚠️  Deletion warning",
        "settings_deletion_warning_body": (
            "When this session is deleted, the agent bundle (.uacragent/) inside "
            "the workspace folder — including all session history, the vector store, "
            "generated outputs, and uploaded file copies — is permanently removed.\n"
            "If the workspace folder is empty afterwards, the folder itself is also "
            "deleted.\n"
            "If you choose a folder that already contains your own files, those "
            "files are not affected — only .uacragent/ is removed."
        ),
        "settings_export_format_label":      "Export format:",
        "settings_extra_instructions_label": "Extra instructions:",
        "settings_docs_section":             "Course Documents",
        "settings_outputs_section":          "Generated Outputs",
        "settings_apply_btn":                "✓  Apply",
        "settings_close_btn":                "Close",
        "settings_add_files_btn":            "Add...",
        "settings_remove_files_btn":         "Remove",
        "settings_open_outputs_btn":         "📂  Open outputs folder",
        "settings_no_workspace":             "No workspace assigned yet.",
        "settings_no_outputs":               "No output files yet.",
        "settings_no_outputs_folder": (
            "No output files yet — outputs folder will be created on first generation."
        ),
        "settings_emb_cache_legend": "✓ installed locally · ⬇ not yet downloaded",
        "settings_emb_local_hint": (
            "Downloaded from HuggingFace on first use, then cached in the app data "
            "folder.  Subsequent uses are instant with no internet required."
        ),
        # Rate-frequency tier section
        "settings_rate_section":   "Request Frequency",
        "settings_rate_tier_label": "API plan tier:",
        "rate_hint_free": (
            "6 s delay · 4 retries  —  for free-tier plans "
            "(Gemini Free: 10 RPM for 2.5-flash, 5 RPM for 2.5-pro). "
            "Safe for the slowest APIs; generation takes longer."
        ),
        "rate_hint_standard": (
            "0.5 s delay · 3 retries  —  for entry-level paid plans "
            "(OpenAI Tier 1: 500 RPM · Gemini Pay-as-you-go Tier 1: 150–300 RPM · "
            "DeepSeek: ~300 RPM dynamic)."
        ),
        "rate_hint_pro": (
            "0.1 s delay · 2 retries  —  for professional paid plans "
            "(OpenAI Tier 2–3: 5 000–10 000 RPM · Gemini Tier 2: 1 000+ RPM)."
        ),
        "rate_hint_unlimited": (
            "No delay · 1 retry  —  for high-capacity or enterprise plans "
            "(OpenAI Tier 4–5: 10 000–15 000 RPM · Gemini Enterprise: 4 000+ RPM)."
        ),
        # Rate-tier suggestion labels (shown when current ≠ provider's default)
        "rate_suggest_mismatch": "💡 Suggested for {provider}: {tier}",
        "rate_suggest_match":    "✓  Matches the suggested tier for {provider}",
        # API key labels / hints
        "api_key_google":   "Google API Key:",
        "api_key_openai":   "OpenAI API Key:",
        "api_key_deepseek": "DeepSeek API Key:",
        "api_key_loaded":   "Loaded from .env",
        "api_key_not_set":  "Not set",
        # Document type section labels
        "doctype_syllabus":     "Syllabus",
        "doctype_lecture_note": "Lecture Notes",
        "doctype_textbook":     "Textbook",
        "doctype_assignment":   "Assignments",
        "doctype_past_exam":    "Past Exams",
        "doctype_other":        "Other",
        # --- Notification / status strings ---
        # New-session initial state
        "new_session_header": "New session",
        "new_session_hint":   "Fill in the settings and click Apply.",
        # Busy / loading labels
        "thinking":           "Thinking…",
        "loading_session":    "Loading session…",
        "indexing_docs":      "Indexing documents…",
        "downloading_model":  "Downloading embedding model… (this may take a while)",
        # Inline pre-flight warnings
        "warn_no_api_key":    (
            "⚠️ No {label} configured. "
            "Open ⚙ Settings → API Key to enter one, then click Apply."
        ),
        "warn_no_embed_key":  (
            "⚠️ Embedding key required. "
            "Open ⚙ Settings → Embedding to configure, then click Apply."
        ),
        "warn_no_course":     (
            "⚠️ Course name required. "
            "Open ⚙ Settings to fill in course details, then click Apply."
        ),
        "warn_no_docs":       (
            "⚠️ No documents loaded. "
            "Add files in ⚙ Settings → Course Documents, then click Apply to index them."
        ),
        # Session-load warnings
        "warn_load_fail":     (
            "⚠️ Could not load session data from {ws}. "
            "The session file may be missing or corrupt."
        ),
        "warn_missing_files": (
            "⚠️  {n} file(s) saved in this session could not be found and will be "
            "skipped during indexing:\n  • {names}\n"
            "Re-add the files in ⚙ Settings if you need them."
        ),
        # Completion / error notices
        "docs_indexed":       "✓ Documents indexed. {status}",
        "error_status":       "Error: {error}",
        "indexing_failed":    "⚠️ Indexing failed: {error}",
        "chat_error":         "⚠️ Error: {error}",
        "request_cancelled":  "Request cancelled.",
        # Chat bubble role labels
        "chat_you":           "You",
        "chat_assistant":     "Assistant",
        # Header / session list fallbacks
        "no_session_loaded":  "No session loaded",
        "untitled_session":   "Untitled session",
        # Welcome message shown for a brand-new session
        "welcome_msg": (
            "Welcome! Open ⚙ Settings to fill in your course details and add "
            "documents, then click Apply to save and index them.\n\n"
            "After that you can ask me anything about the course or use the "
            "quick action buttons to generate study documents."
        ),
        # --- Messagebox titles and bodies ---
        "mb_delete_session_title":   "Delete Session",
        "mb_delete_session_select":  "Select a session to delete.",
        "mb_delete_session_confirm": (
            'Delete session "{name}"?\n\n'
            "This will permanently remove the .uacragent folder inside the "
            "workspace, which contains:\n"
            "  • Session history and settings\n"
            "  • Vector store (chroma_db)\n"
            "  • Generated outputs\n"
            "  • Uploaded file copies\n\n"
            "Your original source files are not affected."
        ),
        "mb_rename_session_title":   "Rename Session",
        "mb_rename_session_select":  "Select a session to rename.",
        "mb_rename_session_prompt":  "Enter a new name for this session:",
        "mb_api_key_title":          "API Key Required",
        "mb_api_key_body": (
            "No {label} found for the selected LLM provider ({provider}).\n\n"
            "Enter your key in ⚙ Settings → API Key, then click Apply."
        ),
        "mb_api_key_send_body": (
            "Enter your {label} in ⚙ Settings → API Key and click  ✓ Apply."
        ),
        "mb_embed_key_title":   "Embedding Key Required",
        "mb_embed_key_body": (
            "Document indexing requires a Google or OpenAI API key for embeddings.\n\n"
            "• Using Gemini or OpenAI as your LLM: the same key is used automatically.\n"
            "• Using DeepSeek: enter a Gemini or OpenAI key in ⚙ Settings → Embedding."
        ),
        "mb_course_name_title": "Course Name Required",
        "mb_course_name_body":  "Please enter a course name in ⚙ Settings.",
        "mb_course_name_send_body": (
            "Please enter a course name in ⚙ Settings and click  ✓ Apply."
        ),
        "mb_indexing_failed_title":  "Indexing Failed",
        "mb_indexing_failed_body":   "Could not index session documents:\n\n{error}\n\n{detail}",
        "mb_indexing_api_detail": (
            "Your API key appears to be missing or invalid.\n\n"
            "Open ⚙ Settings → API Key, enter a valid key, and click Apply."
        ),
        "mb_indexing_other_detail":  "Check your file paths and network connection, then try again.",
        "mb_response_failed_title":  "Response Failed",
        "mb_response_failed_body":   "The agent could not complete your request:\n\n{error}\n\n{detail}",
        "mb_response_api_detail": (
            "Your API key appears to be missing or invalid.\n\n"
            "Open ⚙ Settings → API Key, enter a valid key, and click Apply."
        ),
        "mb_response_other_detail":  "You can try sending your message again.",
        "mb_dl_model_title":   "Download Embedding Model",
        "mb_dl_model_body": (
            "The embedding model has not been downloaded yet.\n\n"
            "  Model : {model_name}\n"
            "  Size  : {size_str}\n"
            "  Saved to : {cache_dir}\n\n"
            "This is a one-time download. Future uses load from the local cache "
            "with no internet connection required.\n\n"
            "Download and continue?"
        ),
        "mb_cannot_create_folder":   "Cannot Create Folder",
        # Output panel per-file action buttons
        "output_open_btn":   "Open",
        "output_copy_btn":   "Copy to…",
        "output_delete_btn": "Delete",
        "mb_copy_title":     "Copied",
        "mb_copy_body":      "Saved to:\n{dest}",
        "mb_copy_fail_title":"Copy Failed",
        "mb_delete_file_title":   "Delete File",
        "mb_delete_file_body":    "Permanently delete:\n{name}?",
        "mb_delete_fail_title":   "Delete Failed",
        "output_copy_dest_title": "Choose destination folder",
        # File attachment / web search
        "attach_files_title": "Select files to attach",
        "attach_supported":   "Supported files",
        "attach_images":      "Images",
        "attach_docs":        "Documents",
        "attach_text":        "Text files",
        "attach_all":         "All files",
        "search_unsupported": "Web search is not supported by the current provider.",
        "files_unsupported":  "File upload is not supported by the current provider.",
        "search_on":          "🌐 Web search ON — will apply to next message",
        "search_off":         "Web search OFF",
        "dnd_drop_label":     "📎  Drop files here to attach",
    },
    "zh_CN": {
        # Session list
        "sessions":           "会话",
        "new_session":        "+ 新建会话",
        "app_settings":       "⚙  应用设置",
        "rename":             "✏  重命名",
        "delete":             "🗑  删除",
        # Chat pane
        "settings_btn":       "⚙  课程设置",
        "quick_actions":      "快速操作",
        "review_summary":     "复习摘要",
        "practice_booklet":   "练习册",
        "mock_exam":          "模拟考试",
        "exam_prediction":    "考试预测",
        "effort_label":       "算力:",
        "low":                "低",
        "medium":             "中",
        "high":               "高",
        # Reasoning mode chip
        "reasoning_mode_label":  "推理:",
        "quick":                 "快速审阅",
        "deep":                  "深度分析",
        "reasoning_quick_desc":  "生成更快，Token 消耗更低。",
        "reasoning_deep_desc":   "推理更全面，Token 消耗更高。",
        "send":               "发送",
        "cancel":             "✕ 取消",
        "placeholder":        "从左侧列表选择会话\n或点击  + 新建  创建新会话。",
        # App Settings dialog
        "app_settings_title": "应用设置",
        "appearance_section": "外观",
        "color_mode_label":   "颜色模式:",
        "light_mode":         "浅色",
        "dark_mode":          "深色",
        "font_size_label":    "字体大小:",
        "font_small":         "小",
        "font_medium":        "中",
        "font_large":         "大",
        "language_label":     "语言:",
        "app_data_label":     "应用数据目录:",
        "app_data_hint":      (
            "索引文件及自动创建的会话工作空间将存储在此处。\n"
            "更改将在下次启动后生效。"
        ),
        "save":               "保存",
        "cancel_btn":         "取消",
        # --- Session Settings dialog ---
        "settings_dialog_title":    "会话设置",
        "settings_banner":          (
            "✏️  在下方编辑任意设置，然后滚动到底部点击  ✓ 应用  以保存并重新索引。"
        ),
        "settings_model_section":   "模型",
        "settings_provider_label":  "提供商:",
        "settings_model_label":     "模型:",
        "settings_api_key_section": "API 密钥",
        "settings_show_key":        "显示",
        "settings_hide_key":        "隐藏",
        "settings_api_key_note": (
            "ℹ️  API 密钥在本次应用窗口的所有会话中共享。\n"
            "在此输入的密钥将应用于所有会话，直到应用关闭或密钥被更改。\n"
            "密钥不会保存到磁盘——每次打开应用时需重新输入，或将其添加到 .env 文件。"
        ),
        "settings_embedding_section":    "嵌入",
        "settings_course_section":       "课程信息",
        "settings_course_name_field":    "课程名称 *",
        "settings_university_field":     "大学",
        "settings_major_field":          "专业 / 院系",
        "settings_course_code_field":    "课程代码",
        "settings_professor_field":      "教授",
        "settings_semester_field":       "学期",
        "settings_exam_section":         "考试选项",
        "settings_exam_type_label":      "考试类型:",
        "settings_exam_format_label":    "考试形式:",
        "settings_exam_duration_label":  "考试时长:",
        "settings_exam_info_label":      "考试说明文件:",
        "settings_browse_btn":           "浏览...",
        "settings_clear_btn":            "清除",
        "settings_workspace_section":    "工作空间与导出",
        "settings_workspace_label":      "工作空间目录:",
        "settings_open_btn":             "打开",
        "settings_reset_btn":            "重置",
        "settings_deletion_warning_title": "⚠️  删除警告",
        "settings_deletion_warning_body": (
            "删除此会话时，工作空间文件夹内的代理包（.uacragent/）——"
            "包括所有会话历史、向量数据库、生成的输出及上传的文件副本——将被永久删除。\n"
            "若删除后工作空间文件夹为空，该文件夹本身也将被删除。\n"
            "若您选择的文件夹已包含其他文件，这些文件不受影响——仅 .uacragent/ 会被删除。"
        ),
        "settings_export_format_label":      "导出格式:",
        "settings_extra_instructions_label": "额外说明:",
        "settings_docs_section":             "课程文档",
        "settings_outputs_section":          "生成的输出",
        "settings_apply_btn":                "✓  应用",
        "settings_close_btn":                "关闭",
        "settings_add_files_btn":            "添加...",
        "settings_remove_files_btn":         "删除",
        "settings_open_outputs_btn":         "📂  打开输出文件夹",
        "settings_no_workspace":             "尚未分配工作空间。",
        "settings_no_outputs":               "暂无输出文件。",
        "settings_no_outputs_folder": (
            "暂无输出文件——将在首次生成时创建输出文件夹。"
        ),
        "settings_emb_cache_legend": "✓ 已下载  · ⬇ 尚未下载",
        "settings_emb_local_hint": (
            "首次使用时从 HuggingFace 下载，随后缓存在应用数据文件夹中。"
            "后续使用无需联网，速度即时。"
        ),
        # Rate-frequency tier section
        "settings_rate_section":   "请求频率",
        "settings_rate_tier_label": "API 计划等级:",
        "rate_hint_free": (
            "6 秒延迟 · 重试 4 次  —  适用于免费计划"
            "（Gemini 免费版：2.5-flash 10 RPM，2.5-pro 5 RPM）。"
            "对最慢的 API 安全可靠，但生成时间较长。"
        ),
        "rate_hint_standard": (
            "0.5 秒延迟 · 重试 3 次  —  适用于入门付费计划"
            "（OpenAI Tier 1：500 RPM · Gemini 按量计费 Tier 1：150–300 RPM · "
            "DeepSeek：约 300 RPM 动态限速）。"
        ),
        "rate_hint_pro": (
            "0.1 秒延迟 · 重试 2 次  —  适用于专业付费计划"
            "（OpenAI Tier 2–3：5 000–10 000 RPM · Gemini Tier 2：1 000+ RPM）。"
        ),
        "rate_hint_unlimited": (
            "无延迟 · 重试 1 次  —  适用于高容量或企业计划"
            "（OpenAI Tier 4–5：10 000–15 000 RPM · Gemini Enterprise：4 000+ RPM）。"
        ),
        # Rate-tier suggestion labels
        "rate_suggest_mismatch": "💡 {provider} 建议等级：{tier}",
        "rate_suggest_match":    "✓  当前等级与 {provider} 的建议匹配",
        # API key labels / hints
        "api_key_google":   "Google API 密钥:",
        "api_key_openai":   "OpenAI API 密钥:",
        "api_key_deepseek": "DeepSeek API 密钥:",
        "api_key_loaded":   "已从 .env 加载",
        "api_key_not_set":  "未设置",
        # Document type section labels
        "doctype_syllabus":     "教学大纲",
        "doctype_lecture_note": "讲义",
        "doctype_textbook":     "教材",
        "doctype_assignment":   "作业",
        "doctype_past_exam":    "历年试卷",
        "doctype_other":        "其他",
        # --- Notification / status strings ---
        # New-session initial state
        "new_session_header": "新建会话",
        "new_session_hint":   "填写设置后点击应用。",
        # Busy / loading labels
        "thinking":           "思考中…",
        "loading_session":    "正在加载会话…",
        "indexing_docs":      "正在索引文档…",
        "downloading_model":  "正在下载嵌入模型…（可能需要较长时间）",
        # Inline pre-flight warnings
        "warn_no_api_key":    (
            "⚠️ 未配置 {label}。"
            "请在 ⚙ 设置 → API Key 中输入，然后点击应用。"
        ),
        "warn_no_embed_key":  (
            "⚠️ 需要嵌入密钥。"
            "请在 ⚙ 设置 → 嵌入 中配置，然后点击应用。"
        ),
        "warn_no_course":     (
            "⚠️ 需要课程名称。"
            "请在 ⚙ 设置 中填写课程信息，然后点击应用。"
        ),
        "warn_no_docs":       (
            "⚠️ 未加载文档。"
            "请在 ⚙ 设置 → 课程文档 中添加文件，然后点击应用进行索引。"
        ),
        # Session-load warnings
        "warn_load_fail":     (
            "⚠️ 无法从 {ws} 加载会话数据。"
            "会话文件可能丢失或损坏。"
        ),
        "warn_missing_files": (
            "⚠️  此会话中保存的 {n} 个文件未找到，索引时将跳过：\n  • {names}\n"
            "如有需要，请在 ⚙ 设置 中重新添加。"
        ),
        # Completion / error notices
        "docs_indexed":       "✓ 文档已索引。{status}",
        "error_status":       "错误：{error}",
        "indexing_failed":    "⚠️ 索引失败：{error}",
        "chat_error":         "⚠️ 错误：{error}",
        "request_cancelled":  "请求已取消。",
        # Chat bubble role labels
        "chat_you":           "您",
        "chat_assistant":     "助手",
        # Header / session list fallbacks
        "no_session_loaded":  "未加载会话",
        "untitled_session":   "未命名会话",
        # Welcome message shown for a brand-new session
        "welcome_msg": (
            "欢迎！请点击 ⚙ 设置 填写课程信息并添加文档，"
            "然后点击应用进行保存和索引。\n\n"
            "完成后，您可以向我提问课程相关问题，"
            "或使用快速操作按钮生成学习文档。"
        ),
        # --- Messagebox titles and bodies ---
        "mb_delete_session_title":   "删除会话",
        "mb_delete_session_select":  "请先选择一个会话后再删除。",
        "mb_delete_session_confirm": (
            '删除会话"{name}"？\n\n'
            "这将永久删除工作空间内的 .uacragent 文件夹，其中包含：\n"
            "  • 会话历史与设置\n"
            "  • 向量数据库（chroma_db）\n"
            "  • 生成的输出\n"
            "  • 上传的文件副本\n\n"
            "您的原始源文件不受影响。"
        ),
        "mb_rename_session_title":   "重命名会话",
        "mb_rename_session_select":  "请先选择一个会话后再重命名。",
        "mb_rename_session_prompt":  "为此会话输入新名称：",
        "mb_api_key_title":          "需要 API 密钥",
        "mb_api_key_body": (
            "未找到所选 LLM 提供商（{provider}）的 {label}。\n\n"
            "请在 ⚙ 设置 → API 密钥 中输入密钥，然后点击应用。"
        ),
        "mb_api_key_send_body": (
            "请在 ⚙ 设置 → API 密钥 中输入 {label}，然后点击  ✓ 应用。"
        ),
        "mb_embed_key_title":   "需要嵌入密钥",
        "mb_embed_key_body": (
            "文档索引需要 Google 或 OpenAI API 密钥来生成嵌入向量。\n\n"
            "• 使用 Gemini 或 OpenAI 作为 LLM：相同密钥将自动使用。\n"
            "• 使用 DeepSeek：请在 ⚙ 设置 → 嵌入 中输入 Gemini 或 OpenAI 密钥。"
        ),
        "mb_course_name_title": "需要课程名称",
        "mb_course_name_body":  "请在 ⚙ 设置 中输入课程名称。",
        "mb_course_name_send_body": (
            "请在 ⚙ 设置 中填写课程名称，然后点击  ✓ 应用。"
        ),
        "mb_indexing_failed_title":  "索引失败",
        "mb_indexing_failed_body":   "无法对会话文档进行索引：\n\n{error}\n\n{detail}",
        "mb_indexing_api_detail": (
            "您的 API 密钥似乎缺失或无效。\n\n"
            "请在 ⚙ 设置 → API 密钥 中输入有效密钥，然后点击应用。"
        ),
        "mb_indexing_other_detail":  "请检查文件路径和网络连接，然后重试。",
        "mb_response_failed_title":  "响应失败",
        "mb_response_failed_body":   "代理无法完成您的请求：\n\n{error}\n\n{detail}",
        "mb_response_api_detail": (
            "您的 API 密钥似乎缺失或无效。\n\n"
            "请在 ⚙ 设置 → API 密钥 中输入有效密钥，然后点击应用。"
        ),
        "mb_response_other_detail":  "您可以重新尝试发送消息。",
        "mb_dl_model_title":   "下载嵌入模型",
        "mb_dl_model_body": (
            "该嵌入模型尚未下载。\n\n"
            "  模型：{model_name}\n"
            "  大小：{size_str}\n"
            "  保存至：{cache_dir}\n\n"
            "这是一次性下载。以后将从本地缓存加载，无需联网。\n\n"
            "是否下载并继续？"
        ),
        "mb_cannot_create_folder":   "无法创建文件夹",
        # Output panel per-file action buttons
        "output_open_btn":   "打开",
        "output_copy_btn":   "复制到…",
        "output_delete_btn": "删除",
        "mb_copy_title":     "已复制",
        "mb_copy_body":      "已保存到：\n{dest}",
        "mb_copy_fail_title":"复制失败",
        "mb_delete_file_title":   "删除文件",
        "mb_delete_file_body":    "永久删除：\n{name}？",
        "mb_delete_fail_title":   "删除失败",
        "output_copy_dest_title": "选择目标文件夹",
        # File attachment / web search
        "attach_files_title": "选择要附加的文件",
        "attach_supported":   "支持的文件",
        "attach_images":      "图片",
        "attach_docs":        "文档",
        "attach_text":        "文本文件",
        "attach_all":         "所有文件",
        "search_unsupported": "当前提供商不支持网络搜索。",
        "files_unsupported":  "当前提供商不支持文件上传。",
        "search_on":          "🌐 网络搜索已开启 — 将应用于下一条消息",
        "search_off":         "网络搜索已关闭",
        "dnd_drop_label":     "📎  拖放文件以附加",
    },
}

# ---------------------------------------------------------------------------
# Appearance: color palettes and font sizes
# ---------------------------------------------------------------------------
_THEME_COLORS: dict[str, dict[str, str]] = {
    "light": {
        # Surfaces
        "window_bg":      "#f0f3f9",   # soft blue-tinted main surface
        "sidebar_bg":     "#e8ecf5",   # cooler sidebar panel
        "paned_bg":       "#c8d0e0",   # thin sash divider
        "text_bg":        "#ffffff",   # chat area
        "input_bg":       "#ffffff",   # input box
        # Text
        "text_fg":        "#1a2744",   # dark navy body text
        "input_fg":       "#1a2744",
        "status_fg":      "#6b7280",   # muted secondary label
        # Session listbox
        "lb_bg":          "#e8ecf5",
        "lb_fg":          "#1a2744",
        "lb_sel_bg":      "#1b3167",   # logo navy selection
        "lb_sel_fg":      "#ffffff",
        # Chat bubbles
        "user_fg":        "#1b3167",   # logo navy for user messages
        "assist_fg":      "#b06000",   # warm amber for assistant label
        "assist_body":    "#2d3748",   # dark slate body text
        "system_fg":      "#6b7280",   # muted gray system messages
        # Chat bubble backgrounds
        "user_bubble_bg":     "#e8f0fe",   # soft blue tint for user bubbles
        "user_bubble_border": "#c5d5f0",   # subtle blue ring
        "asst_bubble_bg":     "#fdf6ee",   # soft warm tint for assistant bubbles
        "asst_bubble_border": "#f0dfc8",   # subtle amber ring
        # Links inside chat
        "link_fg":        "#1b3167",
        "link_folder_fg": "#6b7280",
        # Primary action button (Send, Apply)
        "btn_primary_bg":    "#f5a623",   # logo gold
        "btn_primary_fg":    "#1a2744",
        "btn_primary_hover": "#e8961a",   # darker gold on hover
        # Rounded input border
        "input_border":   "#cdd4e8",   # subtle blue-gray ring
        # Overlay scrollbar — pill only (bg matches content so track is invisible)
        "sb_color":       "#9aa5be",   # pill colour
        "sb_bg":          "#ffffff",   # match text_bg → track disappears
        # Quick-action chip buttons
        "qa_bg":          "#edf0f8",   # chip fill
        "qa_fg":          "#3d4f74",   # chip text
        "qa_bg_hover":    "#dce3f2",   # chip hover
        # Cancel button (replaces Send while busy)
        "btn_cancel_bg":    "#e53e3e",   # red
        "btn_cancel_fg":    "#ffffff",
        "btn_cancel_hover": "#c53030",   # darker red on hover
        # Session list item hover
        "lb_hover_bg":    "#dfe4f0",
        # Info notice box (API key scope)
        "info_bg":        "#e8f4fd",
        "info_border":    "#90caf9",
        "info_fg":        "#0d47a1",
        # Warning box (workspace deletion)
        "warn_bg":        "#fff3e0",
        "warn_border":    "#e65100",
        "warn_title_fg":  "#bf360c",
        "warn_body_fg":   "#4e342e",
        # Alternating rows in file lists
        "row_even_bg":    "#f7f7f7",
        "row_odd_bg":     "#ffffff",
    },
    "dark": {
        # Surfaces — neutral dark-gray palette (mirrors light mode design language)
        "window_bg":      "#1a1d23",   # deep neutral dark (main surface)
        "sidebar_bg":     "#14171c",   # slightly darker sidebar
        "paned_bg":       "#14171c",
        "text_bg":        "#252830",   # chat area: medium dark card
        "input_bg":       "#1e2128",   # input slightly lighter than window_bg
        # Text
        "text_fg":        "#e2e8f0",   # near-white body text
        "input_fg":       "#e2e8f0",
        "status_fg":      "#8892a4",   # muted neutral gray
        # Session listbox
        "lb_bg":          "#14171c",
        "lb_fg":          "#c4cdd8",   # light neutral items
        "lb_sel_bg":      "#2952c4",   # accent blue selection (kept from light)
        "lb_sel_fg":      "#ffffff",
        # Chat bubbles
        "user_fg":        "#7eb0f0",   # soft cornflower blue
        "assist_fg":      "#f5a623",   # logo gold for assistant label (unchanged)
        "assist_body":    "#c4cdd8",   # light neutral body text
        "system_fg":      "#8892a4",   # muted neutral system messages
        # Chat bubble backgrounds
        "user_bubble_bg":     "#1e2533",   # soft blue-tinted dark
        "user_bubble_border": "#2a3650",   # subtle blue ring
        "asst_bubble_bg":     "#272318",   # subtle warm tint for assistant
        "asst_bubble_border": "#3d3224",   # subtle amber ring
        # Links inside chat
        "link_fg":        "#7eb0f0",
        "link_folder_fg": "#8892a4",
        # Primary action button
        "btn_primary_bg":    "#f5a623",   # same logo gold
        "btn_primary_fg":    "#1a2744",
        "btn_primary_hover": "#e8961a",   # darker gold on hover
        # Rounded input border
        "input_border":   "#353a45",   # neutral dark ring
        # Overlay scrollbar — pill only (bg matches content so track is invisible)
        "sb_color":       "#4a5568",   # neutral gray pill
        "sb_bg":          "#252830",   # match text_bg → track disappears
        # Quick-action chip buttons
        "qa_bg":          "#2d3140",   # chip fill
        "qa_fg":          "#9aa8c0",   # chip text
        "qa_bg_hover":    "#363c50",   # chip hover
        # Cancel button (replaces Send while busy)
        "btn_cancel_bg":    "#e53e3e",   # red — same as light
        "btn_cancel_fg":    "#ffffff",
        "btn_cancel_hover": "#c53030",   # darker red on hover
        # Session list item hover
        "lb_hover_bg":    "#1e2230",
        # Info notice box (API key scope) — dark mode
        "info_bg":        "#1a2a3a",
        "info_border":    "#2952c4",
        "info_fg":        "#7eb0f0",
        # Warning box (workspace deletion) — dark mode
        "warn_bg":        "#2d1f0f",
        "warn_border":    "#c26a00",
        "warn_title_fg":  "#f5a623",
        "warn_body_fg":   "#c4a882",
        # Alternating rows in file lists — dark mode
        "row_even_bg":    "#2d3140",
        "row_odd_bg":     "#252830",
    },
}

_FONT_SIZE_VALUES: dict[str, int] = {
    "small":  13,
    "medium": 15,
    "large":  17,
}


# ---------------------------------------------------------------------------
# OS helpers
# ---------------------------------------------------------------------------
def _open_in_os(path: str, *, reveal_folder: bool = False) -> None:
    """Open *path* in the default OS application.

    Parameters
    ----------
    path:
        File or directory path to open.
    reveal_folder:
        When ``True`` and on Windows, open Explorer on *path* as a folder
        rather than launching the folder's default handler.  On macOS and
        Linux the same ``open`` / ``xdg-open`` command handles both files
        and directories correctly so this flag has no effect there.
    """
    system = platform.system()
    try:
        if system == "Darwin":
            proc = subprocess.Popen(["open", path])
            threading.Thread(target=proc.wait, daemon=True).start()
        elif system == "Windows":
            if reveal_folder:
                proc = subprocess.Popen(["explorer", path])
                threading.Thread(target=proc.wait, daemon=True).start()
            else:
                os.startfile(path)  # type: ignore[attr-defined]
        else:
            proc = subprocess.Popen(["xdg-open", path])
            threading.Thread(target=proc.wait, daemon=True).start()
    except Exception:
        pass


def _open_file_in_os(path: str) -> None:
    """Open *path* in the OS default application for that file type."""
    _open_in_os(path, reveal_folder=False)


def _open_folder_in_os(path: str) -> None:
    """Open *path* as a directory in the OS file manager."""
    _open_in_os(path, reveal_folder=True)


def _strip_markdown(text: str) -> str:
    """Remove common Markdown syntax for display in a plain Text widget.

    Strips bold/italic markers, ATX headings, bullet/horizontal-rule lines,
    inline code backticks, and link syntax.  Intentionally simple — the goal
    is legibility in a monospaced plain-text box, not perfect round-tripping.
    """
    # Bold / italic: **, __, *, _ (keep content, drop markers)
    text = re.sub(r'\*{1,3}(.*?)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,3}(.*?)_{1,3}', r'\1', text)
    # ATX headings: "# Title" → "Title"
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Horizontal rules
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
    # Inline code: `code`
    text = re.sub(r'`([^`]*)`', r'\1', text)
    # Links: [text](url) → text
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
    # Bullet/numbered list markers: leading "- ", "* ", "1. "
    text = re.sub(r'^(\s*)[-*]\s+', r'\1• ', text, flags=re.MULTILINE)
    text = re.sub(r'^(\s*)\d+\.\s+', r'\1', text, flags=re.MULTILINE)
    return text


def _fmt_dt(iso: str) -> str:
    """Format an ISO timestamp for display in the session list."""
    try:
        dt = datetime.fromisoformat(iso).astimezone()
        return dt.strftime("%b %d, %Y")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
