"""Build-time patcher: inject the a11y web payload into gradio's js= kwarg.

Upstream app.py builds its js= entry inline (realtime main.js in client
mode, else None). We replace the whole entry with a call to a helper,
_applio_a11y_js(client_mode), that concatenates assets/applio_a11y.js
(dev: now_dir-relative; frozen: sys._MEIPASS fallback - the asset ships
via the ("assets", "assets") datas; setup_bundled_resources does NOT copy
the payload out to the data dir) plus the realtime main.js in client mode
(frozen: setup_bundled_resources copies it next to now_dir), and returns
None when neither file exists - upstream's own no-JS behavior.
Run standalone: venv_macos/bin/python patches/patch_web_a11y_payload.py app.py
"""

import re
import sys

MARKER = "_APPLIO_A11Y_JS_"

JS_ANCHOR = re.compile(
    r'"js": \(\n'
    r"(?P<body>(?:.*\n)*?)"
    r"(?P<close>\s*\),\n)"  # the entry's closing paren before the dict close
)

HELPER = '''def _applio_a11y_js(client_mode):  # {marker}
    """Fork (a11y): web payload JS + optional realtime client JS."""
    parts = []
    for cand in (
        os.path.join(now_dir, "assets", "applio_a11y.js"),
        os.path.join(getattr(sys, "_MEIPASS", now_dir), "assets", "applio_a11y.js"),
    ):
        try:
            if os.path.exists(cand):
                parts.append(pathlib.Path(cand).read_text(encoding="utf-8"))
                break
        except Exception:
            pass
    if client_mode:
        parts.append(
            pathlib.Path(os.path.join(now_dir, "tabs", "realtime", "main.js")).read_text()
        )
    return "\\n;\\n".join(parts) if parts else None


'''

DEF_ANCHOR = "def launch_gradio("


def patch_app(content):
    if MARKER in content:
        return content, "already"
    idx = content.find(DEF_ANCHOR)
    if idx == -1:
        print("Pattern not found: def launch_gradio(")
        return content, "miss"
    # app.py has TWO "js": ( entries - a dead `if not GRADIO_6` fallback in
    # the module-level gr.Blocks and the live GRADIO_6 one inside
    # launch_gradio. Search from the def so only the live entry is touched.
    m = JS_ANCHOR.search(content, idx)
    if not m:
        print('Pattern not found: "js": ( ... ) entry in launch_gradio')
        return content, "miss"
    # Replace the inline js= entry with the helper call (the css entry above
    # it is not part of the match and stays untouched).
    content = (
        content[: m.start()]
        + '"js": _applio_a11y_js(client_mode),\n'
        + content[m.end() :]
    )
    # Insert the helper immediately before launch_gradio, which calls it
    # (re-located on the spliced text: no ordering assumption).
    idx = content.find(DEF_ANCHOR)
    content = content[:idx] + HELPER.format(marker=MARKER) + content[idx:]
    return content, "patched"


if __name__ == "__main__":
    path = sys.argv[1]
    with open(path, "r", encoding="utf-8") as fh:
        src = fh.read()
    out, status = patch_app(src)
    if status in ("patched", "already"):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(out)
        print(f"patch_app: {status}")
        sys.exit(0)
    print(f"patch_app: {status}")
    sys.exit(2)
