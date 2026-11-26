"""The path patcher applied to rvc/train/train.py.

It decides where training finds its logs folder, and it used to write
/tmp/applio_debug.txt at every training start. The debug file is now written
only when APPLIO_DEBUG is set, and a failed write must not stop training
(it did in the App Sandbox, where /tmp is not writable).
"""

import importlib.util
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_patcher():
    spec = importlib.util.spec_from_file_location(
        "patch_train_paths", ROOT / "patches" / "patch_train_paths.py"
    )
    patcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(patcher)
    return patcher


def _patched_functions(source_dir, debug_file):
    """Run the patcher on a copy of train.py and return what it injected."""
    source_dir.mkdir()
    train_py = source_dir / "train.py"
    shutil.copy(ROOT / "rvc" / "train" / "train.py", train_py)

    assert _load_patcher().patch_train_py(str(source_dir))

    source = train_py.read_text(encoding="utf-8")
    start = source.index("_APPLIO_DEBUG_FILE = ")
    end = source.index("current_dir = _get_applio_logs_path()")
    namespace = {}
    exec(compile(source[start:end], "train.py", "exec"), namespace)
    # The tests must never touch the real debug file.
    namespace["_APPLIO_DEBUG_FILE"] = str(debug_file)
    return namespace["_get_applio_logs_path"]


def _no_saved_data_location(monkeypatch, tmp_path):
    """Point HOME at an empty folder, so no runtime_paths.json is found."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("APPLIO_DEBUG", raising=False)


def test_no_debug_file_without_the_flag(tmp_path, monkeypatch):
    _no_saved_data_location(monkeypatch, tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("APPLIO_DATA_PATH", str(data))
    debug_file = tmp_path / "applio_debug.txt"

    get_logs_path = _patched_functions(tmp_path / "src", debug_file)

    assert get_logs_path() == str(data)
    assert not debug_file.exists()


def test_debug_file_with_the_flag(tmp_path, monkeypatch):
    _no_saved_data_location(monkeypatch, tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("APPLIO_DATA_PATH", str(data))
    monkeypatch.setenv("APPLIO_DEBUG", "1")
    debug_file = tmp_path / "applio_debug.txt"

    get_logs_path = _patched_functions(tmp_path / "src", debug_file)

    assert get_logs_path() == str(data)
    assert debug_file.read_text(encoding="utf-8") == (
        f"=== _get_applio_logs_path (train.py): using env var: {data}\n"
    )


def test_unwritable_debug_file_does_not_stop_training(tmp_path, monkeypatch):
    _no_saved_data_location(monkeypatch, tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("APPLIO_DATA_PATH", str(data))
    monkeypatch.setenv("APPLIO_DEBUG", "1")
    missing_folder = tmp_path / "missing"

    get_logs_path = _patched_functions(
        tmp_path / "src", missing_folder / "applio_debug.txt"
    )

    assert get_logs_path() == str(data)
    assert not missing_folder.exists()
