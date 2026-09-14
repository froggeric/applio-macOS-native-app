"""Build-time patcher: expose /applio-a11y/progress on the Gradio app.

Upstream app.py passes prevent_thread_lock=client_mode (False in the app), so
launch() blocks and never returns — everything after the launch call is dead
code in the normal path. We flip the kwarg, register our routes on the
returned FastAPI app, and keep the calling thread alive so launch_gradio()
STILL never returns (the wrapper's supervisor contract). The TensorBoard
proxy below the insertion point stays dead in normal mode — status quo.

Also EXTENDS upstream's allowed_paths list (3ea5259b ships
allowed_paths = ["logs"] for the blender's save target): gradio only serves
output files from cwd+temp by default (gradio/processing_utils._check_allowed),
and in the frozen app cwd is the bundle — converted audio written to
user-chosen dirs (next to the input file, a batch output dir, or the data
dir) raises InvalidPathError in postprocess, so the file exists on disk but
never loads in the UI. The fork appends its entries to the SAME kwarg — a
second allowed_paths kwarg would be a SyntaxError (keyword repeated).
Resolved at LAUNCH time: home covers the default data dir (~/Applio) and
user-picked paths under ~; the env entry covers a first-run data location
chosen OUTSIDE home (macos_wrapper sets APPLIO_DATA_PATH in-process before
Gradio runs). The `if p` filter drops the None when the env is unset (dev) —
gradio's abspath stringifies a None into a bogus `<cwd>/None` entry (no
crash; the filter is hygiene against that).
Run standalone: venv_macos/bin/python patches/patch_progress_routes.py app.py
"""

import re
import sys

MARKER = "_APPLIO_A11Y_ROUTES_"

KWARG_ANCHOR = re.compile(r"prevent_thread_lock=client_mode,(?P<nl>\s*\n)")
# Upstream's own entry (3ea5259b): `allowed_paths = ["logs"],` — tolerate
# both spacings in case their formatter normalizes the `=` padding.
ALLOWED_ANCHOR = re.compile(r'allowed_paths\s*=\s*\["logs"\],(?P<nl>\s*\n)')
TB_ANCHOR = "    from rvc.lib.tools.launch_tensorboard import get_tb_url"

ALLOWED_PATHS_EXT = (
    # Replaces upstream's `allowed_paths = ["logs"],` line with the same list
    # PLUS the fork's runtime-resolved entries. No indent on the first line:
    # the anchor's own line keeps its leading spaces (the match starts at
    # "allowed_paths"), so they prefix this. Trailing comma comes after the
    # closing bracket; the anchor's newline is reproduced via \g<nl>.
    'allowed_paths=["logs"]\n'
    "        + [\n"
    "            p\n"
    '            for p in (os.path.expanduser("~"),'
    ' os.environ.get("APPLIO_DATA_PATH"))\n'
    "            if p\n"
    "        ],"
)

INJECTED = """    # {marker}
    try:
        import applio_progress_api

        applio_progress_api.register_routes(app)
    except Exception:
        pass
    if not client_mode:
        import time as _applio_time

        while True:  # keep this backend thread alive; launch() no longer blocks
            _applio_time.sleep(5)
"""


def patch_app(content):
    if MARKER in content:
        return content, "already"
    if not KWARG_ANCHOR.search(content):
        print("Pattern not found: prevent_thread_lock=client_mode")
        return content, "miss"
    content = KWARG_ANCHOR.sub(
        "prevent_thread_lock=True,  # " + MARKER + "\\g<nl>",
        content,
        count=1,
    )
    if not ALLOWED_ANCHOR.search(content):
        print('Pattern not found: allowed_paths = ["logs"]')
        return content, "miss"
    content = ALLOWED_ANCHOR.sub(ALLOWED_PATHS_EXT + "\\g<nl>", content, count=1)
    idx = content.find(TB_ANCHOR)
    if idx == -1:
        print("Pattern not found: tensorboard import anchor")
        return content, "miss"
    block = INJECTED.format(marker=MARKER)
    content = content[:idx] + block + content[idx:]
    return content, "patched"


if __name__ == "__main__":
    path = sys.argv[1]
    with open(path, "r", encoding="utf-8") as fh:
        src = fh.read()
    out, status = patch_app(src)
    if status in ("patched", "already"):
        with open(path, "w", encoding="utf8") as fh:
            fh.write(out)
        print(f"patch_app: {status}")
        sys.exit(0)
    print(f"patch_app: {status}")
    sys.exit(2)
