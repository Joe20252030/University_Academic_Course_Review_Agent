# UACRAgent v0.3.1 — Stability & Safety Patch

**Release date:** 2026-06-01

This is a patch release focused entirely on stability, safety, and correctness.
No new features are added. All changes are fixes to bugs and gaps identified
during a comprehensive production audit of the v0.3.0 codebase.

---

## Critical fixes

### Fatal crash on window close
Closing the app while an LLM stream or indexing operation was in-flight caused
a fatal Python error:

```
Fatal Python error: PyEval_RestoreThread: the function must be called with the
GIL held, after Python initialization and before Python finalization, but the
GIL is released (the current Python thread state is NULL)
```

Root cause: `destroy()` was called immediately, the main thread exited, and
Python's shutdown sequence killed daemon worker threads mid-execution while
they still held or were waiting for the GIL.

**Fix:** `_on_close` now sets the cancel event first (workers stop at the next
streaming chunk boundary), then defers `destroy()` by 200 ms so all threads
exit cleanly before the window tears down.

---

### `TclError: can't delete Tcl command` on close
Closing the app also sometimes raised:

```
_tkinter.TclError: can't delete Tcl command
```

Root cause: the elapsed-timer ticker was re-registering itself via `after()`
during `destroy()`'s widget teardown, hitting a Tcl command that had already
been unregistered.

**Fix:** the timer is cancelled explicitly in `_on_close` before the deferred
destroy. The `_do_destroy()` method also catches `TclError` as a last-resort
guard.

---

### Plain-text paste freezes the app (macOS)
Pasting any plain text into the chat input caused a multi-second UI freeze.

Root cause: `PIL.ImageGrab.grabclipboard()` runs
`osascript -e "get the clipboard as «class PNGf»"` synchronously on the Tkinter
main thread. On macOS, this subprocess can block for several seconds when the
clipboard holds plain text, freezing the entire event loop.

**Fix:** a new `_clipboard_has_image()` helper checks for image UTIs using
`AppKit.NSPasteboard.types()` (< 1 ms, no subprocess). PIL is only invoked when
image data is actually present.

---

## Other bug fixes

### Document ingestion
- **Per-file error recovery** — a single bad file (corrupted PDF, unsupported
  extension, encoding error) no longer aborts the entire indexing run. It is
  skipped with a logged warning; other files are processed normally. If every
  file fails, a consolidated error lists each failure.
- **Non-UTF-8 text files** — files encoded in Latin-1, GBK, or other non-UTF-8
  charsets now load correctly with replacement characters instead of raising a
  `UnicodeDecodeError`.
- **Scanned / image-only PDFs** — PDFs with no embedded text layer now produce a
  specific error message naming the file and directing the user to an OCR tool,
  instead of the generic "no document chunks created" message.
- **Large file guard** — files over 300 MB are refused before any I/O to prevent
  out-of-memory crashes; files over 100 MB log a warning.

### Security
- **`[TASK:]` injection via history summary** — the LLM-generated conversation
  summary was injected into the system prompt without sanitisation. A
  `[TASK:mock_exam]` pattern surviving from an earlier user turn could in theory
  cause unintended pipeline triggering. The summary now has `[TASK:` neutralised
  (U+2060 word-joiner) before injection, consistent with all other user-controlled
  fields.
- **`[TASK:]` injection via attachment filenames** — attachment names in the
  system prompt's `attachments_note` were injected verbatim. Each name is now
  passed through `_sanitise()`.
- **CLI `--workspace-id` path-traversal** — the CLI set `workspace_folder`
  directly without the safe-character validation applied by the desktop and API
  layers. `--workspace-id ../../sensitive` could place session files outside the
  intended `cli_run/` directory. The CLI now validates against
  `^[A-Za-z0-9_-]{1,128}$` and exits with a clear error on failure.
- **Non-secret env vars in secret-clearance list** — `EMBEDDING_PROVIDER` and
  `LOCAL_EMBEDDING_MODEL` were included alongside API keys in
  `_runtime_secret_env_vars()`. This silently stripped the user's embedding
  setting from the child process env during an app-data-folder relaunch. Only
  actual API keys are now cleared.

### Desktop UI
- **Temp paste images not deleted on removal** — clipboard-pasted screenshots
  written to `uacr_paste_*.png` temp files were only cleaned up after a send.
  Removing the attachment before sending left the temp file permanently.
  `_remove_attachment` now deletes the file immediately.
- **Session file picker incomplete** — the file dialog offered only
  `.pdf .txt .md .docx .csv`, omitting `.py .js .ts .html .htm .xml .json` that
  the loader already supports. All supported extensions are now listed.
- **`gpt-4o-search-preview` models allowed image attachments** — the vision
  guard was provider-level only; search-preview model variants (which do not
  accept multimodal inputs) were not excluded. `_provider_supports_vision()` now
  also checks the model name.
- **History summarisation rate-limit race** — the trim/summarisation LLM call
  fired immediately after the preceding chat reply with no inter-call delay,
  risking 429 errors on Free-tier plans. `_smart_trim_history` now respects the
  `request_delay` from the active rate tier.

### API
- **Concurrent workspace collision** — two simultaneous `POST /review` calls
  with `workspace_id="default"` shared the same `chroma_db/` directory, causing
  SQLite lock collisions. Requests using `"default"` now receive an isolated
  per-request UUID workspace.

### Export
- **OSErrors escaped unwrapped** — `save_markdown`, `save_docx`, and `save_pdf`
  let disk-full or permission errors propagate as bare `OSError`. All three now
  wrap OS failures in `ExportError` with a human-readable message.

### Minor
- **`_ls()` silently swallowed missing i18n keys** — missing keys were returned
  as raw key strings with no diagnostic. A `WARNING` is now logged.
- **`_on_close` duplicated `_clear_runtime_secrets` logic** — `_on_close` had
  its own hardcoded env-var list instead of delegating to the shared method.
  Consolidated to a single call.

---

## Tests

180 new tests added across 8 new test files. 4 pre-existing test bugs fixed.

**Total: 426 tests, all passing.**

New coverage added for: rate tiers, document-priority weights, reasoning config,
`_HistoryStore` thread-safety, full session serialisation round-trips,
vectorstore manifest and `chroma_is_current`, CSV ingestion edge cases, pipeline
effort config and cancellation paths, settings env-var aliases, and regression
tests for every bug fixed in this release.

---

## Upgrade notes

This is a drop-in replacement for v0.3.0. No configuration changes, migration
steps, or API changes are required. Existing session files, workspaces, and
Chroma indexes are fully compatible.
