# Custom hook for webrtcvad - bypass the broken contrib hook
from PyInstaller.utils.hooks import copy_metadata
try:
    datas = copy_metadata("webrtcvad")
except Exception:
    datas = []
