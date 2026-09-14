# applio_a11y.py
"""Accessibility announcement engine for the Applio native app (fork-only).

Pure-Python decision logic (importable/testable with zero AppKit) plus a thin
poster that matches applio_launcher's _announce_for_accessibility signature
(element, message; userInfo key "AXAnnouncementKey" — verified against
applio_launcher.py:142-151).

Phase 1 scope: job LIFECYCLE announcements only (start/pause/resume/terminal).
No per-tick chatter, no speech synthesis (must never collide with the audio
the user is evaluating). Percentage/epoch milestones are Phase 2.
"""

TERMINAL_STATUSES = {
    "completed",
    "failed",
    "error",
    "cancelled",
    "canceled",
    "interrupted",
}
LIVE_STATUSES = {"running", "paused"}
assert not (
    LIVE_STATUSES & TERMINAL_STATUSES
)  # statuses partition into live/terminal/other


def count_live(snapshot):
    """Live (announceable-resumable) job count: running + paused."""
    return sum(1 for v in snapshot.values() if v.get("status") in LIVE_STATUSES)


class AnnouncementPolicy:
    """Diffs consecutive process snapshots and decides what to announce."""

    def __init__(self, translator=None):
        # Optional key->string callable (applio_i18n.native_tr); identity
        # default keeps messages byte-identical when untranslated.
        self._t = translator or (lambda s: s)
        self._seen = {}  # key -> (status, label, word_key)

    def prime(self, snapshot):
        """Populate _seen from a snapshot WITHOUT emitting events.

        Call once with the first heartbeat's snapshot so a relaunch that finds
        already-running jobs (e.g. an hour-old training) records them silently;
        events() would otherwise announce "Started X" for each of them.
        """
        for key, info in snapshot.items():
            label = f"{info.get('type', 'process')}: {info.get('name') or key}"
            self._seen[key] = (
                info.get("status", "running"),
                label,
                info.get("word_key", key),
            )

    def events(self, snapshot, terminal_words=None):
        """Return [(kind, message)] to announce.

        snapshot: dict key -> {"type": str, "name": str, "status": str}
        kind: "start" | "terminal" | "info"
        terminal_words: optional dict word_key -> word announced when a job
            DISAPPEARS while running/paused (default "finished"). Looked up by
            the word_key captured into _seen at insertion time (defaults to the
            snapshot key), so snapshot keys can carry pids without breaking the
            lookup. The launcher passes the job's stored history status so a
            subprocess that died non-zero announces "failed" instead of
            "finished" — the state file nulls dead entries, so disappearance is
            the only failure signal.
        """
        words = terminal_words or {}
        out = []
        for key, info in snapshot.items():
            status = info.get("status", "running")
            label = f"{info.get('type', 'process')}: {info.get('name') or key}"
            prev = self._seen.get(key, (None, label, key))[0]
            if prev is None:
                if status == "running":
                    out.append(
                        ("start", self._t("Started {label}").format(label=label))
                    )
            elif prev != status:
                if status in TERMINAL_STATUSES:
                    word = self._t(status)  # unknown words fall back to the raw word
                    msg = self._t("{label} {status}").format(label=label, status=word)
                    out.append(("terminal", msg))
                elif status == "paused":
                    out.append(("info", self._t("{label} paused").format(label=label)))
                elif status == "running":
                    out.append(("info", self._t("{label} resumed").format(label=label)))
            self._seen[key] = (status, label, info.get("word_key", key))
        for key in [k for k in self._seen if k not in snapshot]:
            prev_status, label, word_key = self._seen.pop(key)
            if prev_status in LIVE_STATUSES:
                word = self._t(words.get(word_key, "finished"))
                msg = self._t("{label} {status}").format(label=label, status=word)
                out.append(("terminal", msg))
        return out

    def missing_keys(self, snapshot):
        """Keys present in _seen but absent from snapshot (candidates for
        disappearance announcements) — read-only, lets the caller decide
        whether the terminal-words history read is worth doing this tick."""
        return set(self._seen) - set(snapshot)


def post_announcement(element, message):
    """Post an AX announcement from `element` (same arg order as
    applio_launcher._announce_for_accessibility).

    MUST be called on the main thread. Silently no-ops when AppKit is
    unavailable or posting fails (matches the launcher helper's defensive
    style — applio_launcher.py:142-151).
    """
    try:
        from AppKit import (
            NSAccessibilityPostNotification,
            NSAccessibilityAnnouncementRequestedNotification,
        )

        userInfo = {"AXAnnouncementKey": message}
        NSAccessibilityPostNotification(
            element, NSAccessibilityAnnouncementRequestedNotification, userInfo
        )
    except Exception:
        pass
