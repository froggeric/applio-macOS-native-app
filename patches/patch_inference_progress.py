"""
Patch to add progress tracking + cooperative cancel to batch inference in infer.py.

This patch:
1. Injects helper functions for writing ~/Applio/.applio/inference_progress.json
   (atomic os.replace writes, 0o600 perms), reading a cancel flag, and appending
   schema-compatible history entries to process_history.json (fcntl LOCK_EX,
   matching applio_launcher.add_to_history).
2. Rewrites VoiceConverter.convert_audio_batch to:
   - reject concurrent batches (status == "running"),
   - emit per-file progress (processed/converted/skipped/current_file),
   - cooperatively cancel via inference_cancel.flag (no PID kill),
   - append a completed/cancelled/error entry to process_history.json,
   - normalise terminal status (running->completed, cancelling->cancelled),
   - clear a stale cancel flag at start (robust against a stray Stop click).
   TOASTS: since upstream #1271/#1275 landed (merged 2026-08-25), the pristine
   convert_audio_batch fires its own toasts via a module-level _toast helper
   (start, 25/50/75% milestones, terminal, error). The rewrite KEEPS those
   upstream calls verbatim (the fork no longer injects _infer_toast - that
   would duplicate every announcement). Only the concurrent-run raise toast
   is fork-added: it sits BEFORE the body's try, so upstream's except-handler
   can never cover it. Upstream 3.7 turned the module-level _toast into a
   plain print, so step (0) below bridges that helper back onto gradio toasts.
3. Removes the broken infer_pid.txt logic (frozen-CWD write was wrong; and in
   single-process os.getpid() == the whole app, so PID-kill quit the app).
4. (a11y phase 4b) Wraps VoiceConverter.convert_audio's body in a try/except so
   SINGLE conversions also write start/terminal records into the same
   inference_progress.json (SSE-independent: the menu/dashboard/a11y payload
   see them even when the in-app WKWebView's toast stream is dead). The begin
   helper skips every write while a non-single record is running/cancelling, so
   a concurrent batch is never clobbered (and the batch loop's nested
   self.convert_audio calls become tracking no-ops via the same guard).

Modeled on patches/patch_refinegan_legacy_infer.py (same base_path arg contract:
opens os.path.join(base_path, "infer.py")).
"""

import os
import re

_HELPERS_MARKER = "# === Inference Progress Tracking (injected by patch) ==="
_BATCH_MARKER = "_infer_cancel_requested()"
# Present only in the injected convert_audio body (the helpers define
# _infer_single_begin/_infer_single_end, never this variable).
_SINGLE_MARKER = "_infer_single_ctx"


INFER_PROGRESS_HELPERS = r'''
# === Inference Progress Tracking (injected by patch) ===
import json as _infer_json
import time as _infer_time
import os as _infer_os
import datetime as _infer_dt

_INFER_HIST_MAX = 50

def _infer_data_dir():
    # 2-tier, matching patches/patch_process_tracking.py._get_process_state_path.
    # In the frozen app, macos_wrapper.start_gui sets APPLIO_DATA_PATH in-process
    # before Gradio runs, so the in-process Gradio thread sees the same env the
    # launcher reads (env-first). Dev defaults to ~/Applio, matching the launcher fallback.
    return _infer_os.environ.get("APPLIO_DATA_PATH") or _infer_os.path.expanduser("~/Applio")

def _infer_progress_path():
    return _infer_os.path.join(_infer_data_dir(), ".applio", "inference_progress.json")

def _infer_cancel_path():
    return _infer_os.path.join(_infer_data_dir(), ".applio", "inference_cancel.flag")

def _read_infer_progress():
    try:
        with open(_infer_progress_path(), "r", encoding="utf-8") as f:
            return _infer_json.load(f)
    except (IOError, _infer_json.JSONDecodeError):
        return None

def _write_infer_progress(record):
    # Best-effort: tracking must NEVER block inference. Single writer + atomic
    # os.replace => no lock (POSIX/APFS atomic rename). A reader sees the whole
    # old or new file, never a torn write.
    try:
        path = _infer_progress_path()
        _infer_os.makedirs(_infer_os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        fd = _infer_os.open(tmp, _infer_os.O_WRONLY | _infer_os.O_CREAT | _infer_os.O_TRUNC, 0o600)
        with _infer_os.fdopen(fd, "w", encoding="utf-8") as f:
            _infer_json.dump(record, f)
        _infer_os.replace(tmp, path)
    except OSError:
        pass

def _infer_cancel_requested():
    return _infer_os.path.exists(_infer_cancel_path())

def _infer_add_to_history(entry):
    # Schema-compatible with applio_launcher.load_process_history/add_to_history
    # (required: type, started_at, completed_at). fcntl LOCK_EX on <hist>.lock
    # matches the launcher writer (which may read/write concurrently).
    try:
        import fcntl as _infer_fcntl
        hist_path = _infer_os.path.join(_infer_data_dir(), ".applio", "process_history.json")
        _infer_os.makedirs(_infer_os.path.dirname(hist_path), exist_ok=True)
        lock_path = hist_path + ".lock"
        with open(lock_path, "a") as _lf:
            _infer_fcntl.flock(_lf.fileno(), _infer_fcntl.LOCK_EX)
            try:
                hist = {"version": 1, "history": []}
                if _infer_os.path.exists(hist_path):
                    try:
                        with open(hist_path, "r", encoding="utf-8") as f:
                            hist = _infer_json.load(f) or hist
                    except _infer_json.JSONDecodeError:
                        pass
                entry["process_id"] = "inference-%s" % entry.get("started_at")
                hist.setdefault("history", []).insert(0, entry)
                hist["history"] = hist["history"][:_INFER_HIST_MAX]
                tmp = hist_path + ".tmp"
                fd = _infer_os.open(tmp, _infer_os.O_WRONLY | _infer_os.O_CREAT | _infer_os.O_TRUNC, 0o600)
                with _infer_os.fdopen(fd, "w", encoding="utf-8") as f:
                    _infer_json.dump(hist, f, indent=2)
                _infer_os.replace(tmp, hist_path)
            finally:
                _infer_fcntl.flock(_lf.fileno(), _infer_fcntl.LOCK_UN)
    except OSError:
        pass

def _infer_single_begin(model_path, audio_input_path, audio_output_path):
    """Single-conversion tracking (a11y phase 4b): claim inference_progress.json
    for a one-file convert_audio run so the menu/dashboard/a11y payload see it
    even when the toast SSE stream is dead. Returns a ctx dict when this call
    owns the file, else None (every single write is then skipped): a competing
    record with status running/cancelling AND scope != "single" - i.e. a batch,
    whose records carry no scope - must never be clobbered (one atomic-write
    owner at a time). The batch loop's nested self.convert_audio calls hit this
    same guard and become tracking no-ops. Never raises."""
    try:
        existing = _read_infer_progress()
        if (
            existing
            and existing.get("status") in ("running", "cancelling")
            and existing.get("scope") != "single"
        ):
            return None
        started_at = _infer_time.time()
        # NOTE on line packing: the processed/converted/skipped keys are
        # deliberately split across lines - the batch tests locate the batch's
        # initial write via an exact first-occurrence substring of those three
        # keys on ONE line, and this helpers block sits EARLIER in the file.
        record = {
            "version": 1, "type": "inference", "status": "running",
            "scope": "single",
            "model_name": _infer_os.path.basename(model_path or ""),
            "input_folder": _infer_os.path.dirname(audio_input_path or "") or None,
            "output_folder": _infer_os.path.dirname(audio_output_path or "") or None,
            "total": 1,
            "processed": 0,
            "converted": 0, "skipped": 0,
            "current_file": _infer_os.path.basename(audio_input_path or ""),
            "started_at": started_at, "ended_at": None, "elapsed": None,
            "error": None,
        }
        _write_infer_progress(record)
        return {
            "model_name": record["model_name"],
            "output_folder": record["output_folder"],
            "started_at": started_at,
        }
    except Exception:
        return None

def _infer_single_end(ctx, error=None):
    """Terminal write + schema-compatible history append for a single
    conversion. ctx None => no-op (begin skipped: a batch owns the file, or
    begin itself failed). Best-effort: never raises, never breaks the
    conversion itself. elapsed/ended_at mirror the batch record schema the
    launcher reader (_synthesize_inference_proc) and the startup sweep use;
    the history entry carries completed_at (ISO), like the batch's."""
    if not ctx:
        return
    try:
        status = "error" if error else "completed"
        ended_at = _infer_time.time()
        started_at = ctx["started_at"]
        converted = 0 if error else 1
        _write_infer_progress({
            "version": 1, "type": "inference", "status": status,
            "scope": "single",
            "model_name": ctx["model_name"],
            "input_folder": None, "output_folder": ctx["output_folder"],
            "total": 1, "processed": converted, "converted": converted,
            "skipped": 0, "current_file": "",
            "started_at": started_at, "ended_at": ended_at,
            "elapsed": ended_at - started_at, "error": error,
        })
        # Built in a variable rather than passed inline as a dict literal: the
        # batch tests locate the batch's FIRST history call by an exact
        # substring ending in an opening brace, and this block sits earlier.
        entry = {
            "type": "inference", "scope": "single",
            "model_name": ctx["model_name"],
            "started_at": _infer_dt.datetime.fromtimestamp(started_at).isoformat(),
            "completed_at": _infer_dt.datetime.fromtimestamp(ended_at).isoformat(),
            "status": status, "total": 1, "converted": converted, "skipped": 0,
        }
        _infer_add_to_history(entry)
    except Exception:
        pass
# === End Inference Progress Tracking ===
'''


# Anchor regex: spans the method BODY only (the def + docstring are preserved).
# Bookends = the pristine pid-file open and upstream's whole finally block
# (model cleanup + guarded pid-file removal, upstream 3.7); the MIDDLE pin
# (_toast start call) verifies the post-#1275 shape, so a future upstream
# rewrite of the toast text misses here (exit 2) instead of silently
# replacing newer upstream code with this stale replacement.
INFER_BATCH_ANCHOR = re.compile(
    r"        pid = os\.getpid\(\)\n        try:.*?"
    r'_toast\(f"Batch conversion started: \{total\} files"\)\n.*?'
    r"        finally:\n"
    r"            self\.cleanup_model\(\)\n"
    r'            pid_path = os\.path\.join\(now_dir, "assets", "infer_pid\.txt"\)\n'
    r"            if os\.path\.exists\(pid_path\):\n"
    r"                try:\n"
    r"                    os\.remove\(pid_path\)\n"
    r"                except Exception:\n"
    r"                    pass\n",
    re.DOTALL,
)

# Upstream 3.7 turned _toast into a plain print ("the web UI streams engine
# logs"): the batch start / milestone / terminal / failure announcements no
# longer reach the UI as toasts. The fork keeps them as toasts (its announced
# feedback for every user, and the toast layer of its accessibility design) by
# bridging the same helper onto gradio's toast calls. Lazy import + guard: the
# engine must keep working where gradio has no request context (CLI, tests).
INFER_TOAST_ANCHOR = (
    "def _toast(message, warning=False):\n"
    '    """Status message helper (prints to stdout; the web UI streams engine logs)."""\n'
    "    print(message)\n"
)
_TOAST_MARKER = "(gr.Warning if warning else gr.Info)(message)"
INFER_TOAST_BRIDGE = (
    "def _toast(message, warning=False):\n"
    '    """Status message helper: engine log line and UI toast (fork bridge)."""\n'
    "    print(message)\n"
    "    try:\n"
    "        import gradio as gr\n"
    "\n"
    "        (gr.Warning if warning else gr.Info)(message)\n"
    "    except Exception:\n"
    "        pass\n"
)


INFER_BATCH_REPLACEMENT = r"""        # Inference progress tracking (fork): cooperative cancel + progress file
        # + process history, layered onto upstream's #1271/#1275 toast-announced
        # loop. Upstream's _toast calls are kept verbatim - the fork injects NO
        # toast helper of its own (that would double every announcement). The
        # PID-file mechanism is gone on purpose: the frozen-CWD write was broken,
        # and in single-process os.getpid() == the whole app, so PID-kill quit
        # the app.
        existing = _read_infer_progress()
        if existing and existing.get("status") == "running":
            # This raise sits BEFORE the body's try:, so the except-handler
            # toast below can never cover it - announce here, then raise.
            _toast(
                "Batch conversion failed: another batch inference is already running."
                " Stop it first from the Process Dashboard.",
                warning=True,
            )
            raise RuntimeError(
                "Another batch inference is already running. Stop it first from the Process Dashboard."
            )
        _model_name = _infer_os.path.basename(kwargs.get("model_path") or "")
        start_time = _infer_time.time()
        print(f"Converting audio batch '{audio_input_paths}'...")
        audio_files = [
            f
            for f in _infer_os.listdir(audio_input_paths)
            if f.lower().endswith(
                (
                    "wav", "mp3", "flac", "ogg", "opus", "m4a", "mp4",
                    "aac", "alac", "wma", "aiff", "webm", "ac3",
                )
            )
        ]
        print(f"Detected {len(audio_files)} audio files for inference.")
        total = len(audio_files)
        processed = converted = skipped = 0
        _next_milestone = 25
        status = "running"
        _toast(f"Batch conversion started: {total} files")
        _write_infer_progress({
            "version": 1, "type": "inference", "status": status,
            "model_name": _model_name, "input_folder": audio_input_paths,
            "output_folder": audio_output_path, "total": total,
            "processed": 0, "converted": 0, "skipped": 0,
            "current_file": audio_files[0] if audio_files else "",
            "started_at": start_time, "ended_at": None, "elapsed": None, "error": None,
        })
        # Clear any stale cancel flag left by a Stop click on a PREVIOUS, already-
        # finished batch (otherwise this batch would cancel on its first file).
        try:
            _infer_os.remove(_infer_cancel_path())
        except OSError:
            pass
        try:
            # Ensure the output folder exists (otherwise the first convert fails
            # with an opaque soundfile "System error" when the output path does
            # not exist yet). exist_ok=True is a no-op when it already exists.
            # A genuine creation failure (permissions) raises here and is caught
            # below as a clear error instead of soundfile's opaque message.
            _infer_os.makedirs(audio_output_path, exist_ok=True)
            for idx, a in enumerate(audio_files):
                if _infer_cancel_requested():
                    status = "cancelling"
                    _write_infer_progress({
                        "version": 1, "type": "inference", "status": status,
                        "model_name": _model_name, "input_folder": audio_input_paths,
                        "output_folder": audio_output_path, "total": total,
                        "processed": processed, "converted": converted, "skipped": skipped,
                        "current_file": a, "started_at": start_time,
                        "ended_at": None, "elapsed": None, "error": None,
                    })
                    break
                new_input = _infer_os.path.join(audio_input_paths, a)
                new_output = _infer_os.path.splitext(a)[0] + "_output.wav"
                new_output = _infer_os.path.join(audio_output_path, new_output)
                if _infer_os.path.exists(new_output):
                    skipped += 1
                else:
                    self.convert_audio(
                        audio_input_path=new_input,
                        audio_output_path=new_output,
                        **kwargs,
                    )
                    converted += 1
                processed = converted + skipped
                nxt = audio_files[idx + 1] if idx + 1 < total else ""
                _write_infer_progress({
                    "version": 1, "type": "inference", "status": status,
                    "model_name": _model_name, "input_folder": audio_input_paths,
                    "output_folder": audio_output_path, "total": total,
                    "processed": processed, "converted": converted, "skipped": skipped,
                    "current_file": nxt, "started_at": start_time,
                    "ended_at": None, "elapsed": None, "error": None,
                })
                # Milestone toast (upstream #1275): fires at the first file past
                # each threshold (the label carries the threshold). processed
                # < total suppresses the 100% milestone (it would double-announce
                # with the terminal toast); total >= 8 keeps small batches
                # toast-free between start and terminal.
                if (
                    total >= 8
                    and processed < total
                    and processed * 100 // total >= _next_milestone
                ):
                    _toast(f"{processed}/{total} files converted ({_next_milestone}%)")
                    _next_milestone += 25
            # Normalise terminal status (loop exited without raise).
            if status == "running":
                status = "completed"
            elif status == "cancelling":
                status = "cancelled"
            ended_at = _infer_time.time()
            elapsed = ended_at - start_time
            if status == "completed":
                print(f"Conversion completed at '{audio_input_paths}'.")
                print(f"Batch conversion completed in {elapsed:.2f} seconds.")
            _write_infer_progress({
                "version": 1, "type": "inference", "status": status,
                "model_name": _model_name, "input_folder": audio_input_paths,
                "output_folder": audio_output_path, "total": total,
                "processed": processed, "converted": converted, "skipped": skipped,
                "current_file": "", "started_at": start_time,
                "ended_at": ended_at, "elapsed": elapsed, "error": None,
            })
            _toast(
                f"Batch conversion {status}: {converted} converted, "
                f"{skipped} skipped in {elapsed:.0f}s"
            )
            _infer_add_to_history({
                "type": "inference", "model_name": _model_name,
                "started_at": _infer_dt.datetime.fromtimestamp(start_time).isoformat(),
                "completed_at": _infer_dt.datetime.fromtimestamp(ended_at).isoformat(),
                "status": status, "total": total,
                "converted": converted, "skipped": skipped,
            })
        except Exception as _infer_exc:
            ended_at = _infer_time.time()
            elapsed = ended_at - start_time
            _write_infer_progress({
                "version": 1, "type": "inference", "status": "error",
                "model_name": _model_name, "input_folder": audio_input_paths,
                "output_folder": audio_output_path, "total": total,
                "processed": processed, "converted": converted, "skipped": skipped,
                "current_file": "", "started_at": start_time,
                "ended_at": ended_at, "elapsed": elapsed, "error": str(_infer_exc),
            })
            _infer_add_to_history({
                "type": "inference", "model_name": _model_name,
                "started_at": _infer_dt.datetime.fromtimestamp(start_time).isoformat(),
                "completed_at": _infer_dt.datetime.fromtimestamp(ended_at).isoformat(),
                "status": "error", "total": total,
                "converted": converted, "skipped": skipped,
            })
            _toast(f"Batch conversion failed: {_infer_exc}", warning=True)
            raise
        finally:
            self.cleanup_model()
            # Always remove the cancel flag (a post-completion Stop click is a no-op;
            # a fresh batch is not cancelled by a leftover flag - the start-clear above
            # also covers this, but finally makes it robust even if start-clear raced).
            try:
                _infer_os.remove(_infer_cancel_path())
            except OSError:
                pass
"""


# Single-conversion seam (a11y phase 4b): wrap convert_audio's body in a
# try/except so single conversions write start/terminal records via the
# _infer_single_* helpers. Light two-endpoint seam rather than a whole-body
# rewrite: the anchor pins only get_vc (head; after the docstring + model_path
# guard, before any failure-prone work) and the elapsed_time tail - the body
# BETWEEN them is captured and re-emitted verbatim at +4 indent, so upstream
# edits between the endpoints survive the patch. Both endpoints are unique to
# convert_audio file-wide (the batch opens with `pid = os.getpid()` and its
# timing lines use `_infer_time`/different indentation after step (b)).
INFER_SINGLE_HEAD = (
    "        self.get_vc(model_path, sid, inference_engine, onnx_precision)\n" "\n"
)
INFER_SINGLE_ANCHOR = re.compile(
    re.escape(INFER_SINGLE_HEAD)
    + r"        start_time = time\.time\(\)\n(.*?)"
    + r"        elapsed_time = time\.time\(\) - start_time\n",
    re.DOTALL,
)


def _infer_single_wrap(m):
    """re.sub callable for INFER_SINGLE_ANCHOR: re-emit convert_audio's body
    wrapped in the single-conversion tracking try/except. The bare re-raise
    preserves the pristine traceback; tracking helpers swallow their own
    errors, so a tracking failure can never break the conversion. Blank lines
    stay blank; every other captured line gains exactly 4 leading spaces
    (uniform re-indent preserves Python block structure; the wrapped region
    contains no multi-line strings whose content would change)."""
    reindented = "".join(
        ("    " + ln) if ln.strip() else ln
        for ln in m.group(1).splitlines(keepends=True)
    )
    return (
        INFER_SINGLE_HEAD + "        _infer_single_ctx = _infer_single_begin(\n"
        "            model_path, audio_input_path, audio_output_path\n"
        "        )\n"
        "        start_time = time.time()\n"
        "        try:\n"
        + reindented
        + "        except Exception as _infer_single_exc:\n"
        "            _infer_single_end(_infer_single_ctx, error=str(_infer_single_exc))\n"
        "            raise\n"
        "        _infer_single_end(_infer_single_ctx)\n"
        "        elapsed_time = time.time() - start_time\n"
    )


def patch_infer_py(base_path: str) -> bool:
    """Patch infer.py to add batch-inference progress tracking + cancel +
    history, and single-conversion start/terminal tracking.

    Args:
        base_path: Directory containing infer.py (e.g., rvc/infer/)

    Returns:
        True if patched successfully (or already patched), False if the anchor
        could not be found.
    """
    infer_path = os.path.join(base_path, "infer.py")

    if not os.path.exists(infer_path):
        raise FileNotFoundError(f"infer.py not found at {infer_path}")

    with open(infer_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Idempotency: the helpers marker (incl. the single-conversion helpers),
    # the batch-rewrite marker, AND the single-seam marker must ALL be present
    # to consider the file fully patched. Use the patcher's OWN specific
    # markers (NOT a shared early-return marker). helpers_done additionally
    # requires def _infer_single_begin so a file patched by an OLDER version of
    # this patcher (helpers without the single fns) gets the helpers re-injected
    # instead of silently NameError-ing at runtime.
    helpers_done = _HELPERS_MARKER in content and "def _infer_single_begin(" in content
    batch_done = _BATCH_MARKER in content
    single_done = _SINGLE_MARKER in content
    if helpers_done and batch_done and single_done and _TOAST_MARKER in content:
        print("[infer.py inference-progress] Already patched, skipping.")
        return True

    changed = False

    # (0) Bridge upstream's print-only _toast onto gradio toasts (see
    # INFER_TOAST_BRIDGE). Required: a missed anchor means upstream reworked
    # the helper, and the announcements would silently stop reaching the UI.
    toast_done = _TOAST_MARKER in content
    if not toast_done:
        if content.count(INFER_TOAST_ANCHOR) != 1:
            print(
                "[infer.py inference-progress] Could not find upstream's _toast helper "
                f"(found {content.count(INFER_TOAST_ANCHOR)}, expected 1)"
            )
            return False
        content = content.replace(INFER_TOAST_ANCHOR, INFER_TOAST_BRIDGE, 1)
        changed = True

    # (a) Inject helpers before `class VoiceConverter` (unique + stable anchor).
    if not helpers_done:
        if "class VoiceConverter:" not in content:
            print("[infer.py inference-progress] Could not find class VoiceConverter")
            return False
        content = content.replace(
            "class VoiceConverter:",
            INFER_PROGRESS_HELPERS + "\n\nclass VoiceConverter:",
            1,
        )
        changed = True

    # (b) Replace the batch body (regex; the body has a 13-element tuple that
    # makes a literal match fragile).
    if not batch_done:
        new_content, n = INFER_BATCH_ANCHOR.subn(
            INFER_BATCH_REPLACEMENT, content, count=1
        )
        if n == 0:
            print(
                "[infer.py inference-progress] Could not find convert_audio_batch anchor"
            )
            return False
        content = new_content
        changed = True

    # (c) Wrap convert_audio's body for single-conversion tracking.
    if not single_done:
        new_content, n = INFER_SINGLE_ANCHOR.subn(_infer_single_wrap, content, count=1)
        if n == 0:
            print(
                "[infer.py inference-progress] Could not find convert_audio single-tracking anchor"
            )
            return False
        content = new_content
        changed = True

    if changed:
        with open(infer_path, "w", encoding="utf-8") as f:
            f.write(content)
        print("[infer.py inference-progress] Patched successfully")
    else:
        print("[infer.py inference-progress] Already patched, skipping.")
    return True


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python patch_inference_progress.py <base_path>")
        sys.exit(1)

    base_path = sys.argv[1]
    success = patch_infer_py(base_path)
    sys.exit(0 if success else 2)
