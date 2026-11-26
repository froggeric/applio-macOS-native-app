/* Applio a11y web payload (fork-owned; injected via gradio js= on load).
   Regions are created up-front (live regions must exist before updates),
   writes are change-only, and spoken announcements are gated by the payload's
   verbosity (auto-a11y: "verbose" when VoiceOver runs / a11y.speech=on, else
   "off"). The native window-level AX post path was removed (2026-08-23), so
   this live region is THE speech channel for every client; announce.owner
   stays "web" (the per-request native rule is reserved machinery). */
(function () {
  "use strict";
  if (window.__APPLIO_A11Y__) { return; }
  window.__APPLIO_A11Y__ = true;

  var POLL_MS = 2000, BACKOFF_MS = 8000;
  var MILESTONES = [25, 50, 75, 100];
  /* Mirrors applio_a11y.TERMINAL_STATUSES — a status NOT in this list (e.g.
     a batch showing "cancelling" while Stop takes effect) must never be
     announced as a terminal word. */
  var TERMINAL = ["completed", "failed", "error", "cancelled", "canceled", "interrupted"];
  var lastLive = "", lastNav = null, pollFailures = 0;
  var seen = {};      // job key -> {status, ms, info}
  var primed = false;
  var lastOutputText = {};  // textbox elem_id/text -> last recorded value

  /* SELECTORS pinned from a live-DOM session against the installed gradio
     6.20.0 (python app.py + devtools):
     - the accordion container is <div class="block gr-accordion ..."> and
       the open state lives ON the header button (button.label-wrap gains
       the "open" class); block-accordion/gradio-accordion match nothing.
     - tab buttons are <button role="tab" aria-selected data-tab-id> inside
       [role=tablist]; the FIRST document-order match is a top-level tab
       (nested tab groups render inside tabitems, after the top tablist).
       tab-nav/tab-button match nothing. label-wrap, gradio-image,
       gradio-container and [data-testid=toast-body] exist (bundle-grep).
     - since Applio 3.7 the pages are chosen from a sidebar of buttons
       (#applio-navigation) and the page tabs stay hidden; the open page's
       button carries aria-current="page" (assets/app_shell.py). */
  var ACCORDION_BLOCK = ".gr-accordion";
  var ACCORDION_BUTTON = "button.label-wrap";
  var TAB_SELECTED = '[role="tablist"] button[aria-selected="true"]';
  var PAGE_SELECTED = '#applio-navigation button[aria-current="page"]';
  var NAVIGATION = "#applio-navigation";

  function ensureRegions() {
    var root = document.querySelector(".gradio-container") || document.body;
    var live = document.getElementById("applio-a11y-live");
    if (!live) {
      live = document.createElement("div");
      live.id = "applio-a11y-live";
      live.className = "sr-only";
      live.setAttribute("role", "status");
      live.setAttribute("aria-live", "polite");
      live.setAttribute("aria-atomic", "true");
      root.appendChild(live);
      // fresh region: allow the next announce even if identical to the last
      // text written into the (now-removed) previous region
      lastLive = "";
      if (!document.getElementById("applio-a11y-style")) {
        var style = document.createElement("style");
        style.id = "applio-a11y-style";
        style.textContent =
          "#applio-a11y-live.sr-only{position:absolute;width:1px;height:1px;" +
          "overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;}" +
          "#applio-a11y-last{margin:8px 16px;padding:8px 12px;font-size:0.95em;" +
          "border:1px solid rgba(128,128,128,0.4);border-radius:8px;}" +
          "input[type=checkbox]:focus-visible,input[type=radio]:focus-visible{" +
          "outline:2px solid #4c9ffe;outline-offset:2px;}";
        document.head.appendChild(style);
      }
    }
    var last = document.getElementById("applio-a11y-last");
    if (!last) {
      last = document.createElement("div");
      last.id = "applio-a11y-last";
      last.setAttribute("role", "region");
      last.setAttribute("aria-label", "Last result");
      last.textContent = "";
      root.appendChild(last);
    }
    return { live: live, last: last };
  }

  function announce(text) {
    var regions = ensureRegions();
    if (!text || text === lastLive) { return; }
    lastLive = text;
    regions.live.textContent = text;
  }

  function persistResult(text) {
    var regions = ensureRegions();
    var stamp = new Date().toLocaleTimeString();
    regions.last.textContent = stamp + " — " + text;
  }

  /* --- static healing ------------------------------------------------- */

  function healAccordions() {
    document.querySelectorAll(ACCORDION_BLOCK).forEach(function (acc) {
      var btn = acc.querySelector(ACCORDION_BUTTON);
      if (!btn) { return; }
      // live-verified: the "open" class toggles on the header button itself
      // (gradio 6.20 sets no aria-expanded — the gap this heals)
      var open = btn.classList.contains("open") ||
        acc.classList.contains("open") || acc.hasAttribute("open");
      btn.setAttribute("aria-expanded", String(open));
    });
  }

  function healRecordToggles() {
    // Scoped to the realtime "Record Audio (Optional)" accordion: the
    // fork-injected Browse button for record_audio_path is the only stable
    // fork-controlled DOM anchor in it (the record toggle itself has no
    // elem_id), and the toggle is a SIBLING of the path field's column, so
    // the accordion is the smallest correct scope (verified against gradio
    // 6.20.0: Column renders div.column, Button has no .form wrapper, and
    // gradio-column does not exist). The engine Start/Stop pair at the top
    // of the tab is momentary, NOT a toggle, lives outside every accordion,
    // and must not receive aria-pressed.
    var anchor = document.querySelector("#browse-record_audio_path");
    if (!anchor) { return; }
    var scope = anchor.closest(ACCORDION_BLOCK);
    if (!scope) { return; }
    scope.querySelectorAll("button").forEach(function (btn) {
      var t = (btn.textContent || "").trim().toLowerCase();
      if (t === "start" || t === "stop") {
        btn.setAttribute("aria-pressed", String(t === "stop"));
      }
    });
  }

  function healImageAlts() {
    document.querySelectorAll("gradio-image, .image-container").forEach(function (block) {
      var img = block.querySelector("img");
      if (!img || img.getAttribute("alt")) { return; }
      var label = block.querySelector("label span, .icon-button + span");
      if (label && label.textContent.trim()) {
        img.setAttribute("alt", label.textContent.trim());
      }
    });
  }

  /* --- output-textbox mutation announcements (audit webui-semantics-1) -- */

  function announceOutputChanges() {
    document.querySelectorAll('textarea').forEach(function (ta) {
      if (ta === document.activeElement) { return; }  // user typing
      var id = ta.id || ta.name || ta.getAttribute("data-testid") || "";
      if (!id) { return; }
      var value = ta.value || "";
      var prev = lastOutputText[id];
      lastOutputText[id] = value;
      if (!value || prev === undefined || prev === value || !prev) { return; }
      var short = value.length > 120 ? value.slice(0, 120) + "…" : value;
      // Visible record ONLY (re-test round 3, owner decision): output-change
      // speech is gone entirely — the round-2 jobs gate still leaked in the
      // lag windows around job start/terminal, and the live region is a
      // single replacement channel, so jobs own the spoken word. Every
      // change still lands in the Last-result region below.
      persistResult(short);
    });
  }

  /* --- focus restore --------------------------------------------------- */

  document.addEventListener("focusout", function (ev) {
    var el = ev.target;
    if (!el || !el.tagName || el.tagName !== "BUTTON") { return; }
    window.setTimeout(function () {
      if (document.contains(el)) { return; }           // still there: nothing to do
      var anchor = el.id ? document.getElementById(el.id) : null;
      var target = anchor;
      if (!target) {
        var regions = ensureRegions();
        target = regions.last;                         // predictable landing spot
        target.setAttribute("tabindex", "-1");
      }
      try { target.focus(); } catch (e) { /* detached mid-fix */ }
    }, 50);
  }, true);

  /* --- observers -------------------------------------------------------- */

  var healTimer = null;
  function scheduleHeal() {
    if (healTimer) { return; }
    healTimer = window.setTimeout(function () {
      healTimer = null;
      healAccordions(); healRecordToggles(); healImageAlts();
      announceOutputChanges(); readNav();
    }, 250);
  }

  // Accordion open/closed and tab selection flip CLASSES/attributes, which
  // the childList-only MutationObserver below never sees — re-heal on click
  // (capture-phase; we never stopPropagation, gradio's handler still runs
  // and flips the state before the debounced heal reads it).
  document.addEventListener("click", function (ev) {
    var t = ev.target;
    if (t && t.closest && t.closest(ACCORDION_BLOCK)) { scheduleHeal(); }
    if (t && t.closest && t.closest('[role="tablist"]')) { readNav(); }
    // aria-current is set once the page has changed, so read it debounced.
    if (t && t.closest && t.closest(NAVIGATION)) { scheduleHeal(); }
  }, true);

  function readNav() {
    var sel = document.querySelector(PAGE_SELECTED) ||
      document.querySelector(TAB_SELECTED);
    if (sel) {
      var token = (sel.textContent || "").trim();
      if (token && token !== lastNav) { lastNav = token; }
    }
  }

  function observeToasts() {
    var obs = new MutationObserver(function (muts) {
      muts.forEach(function (m) {
        Array.prototype.forEach.call(m.addedNodes || [], function (node) {
          if (!node.querySelectorAll) { return; }
          var bodies = node.querySelectorAll('[data-testid="toast-body"]');
          Array.prototype.forEach.call(bodies, function (b) {
            persistResult(b.textContent.trim());
          });
          if (node.matches && node.matches('[data-testid="toast-body"]')) {
            persistResult(node.textContent.trim());
          }
        });
      });
    });
    obs.observe(document.body, { childList: true, subtree: true });
  }

  /* --- progress polling -------------------------------------------------- */

  function jobLabel(job) {
    var t = job.type || "process";
    if (t === "inference") {
      // Scope-aware (mirrors applio_launcher.inference_job_type): a tracked
      // single conversion must not be announced as "batch inference"; batch
      // records carry no scope.
      t = job.scope === "single" ? "conversion" : "batch inference";
    }
    return t + " " + (job.name || "");
  }

  function failedTail(errors, job) {
    var list = errors || [];
    for (var i = 0; i < list.length; i++) {
      var e = list[i];
      if (e.type === job.type && e.name === job.name && e.tail) {
        return String(e.tail).slice(-400);
      }
    }
    return "";
  }

  function handlePayload(payload) {
    var owner = payload && payload.announce && payload.announce.owner;
    var verbosity = (payload && payload.settings && payload.settings.verbosity) || "standard";
    var words = (payload && payload.words) || {};
    var jobs = (payload && payload.jobs) || [];
    var errors = (payload && payload.errors) || [];
    var current = {};
    jobs.forEach(function (job) { current[job.key] = job; });

    if (!primed) {
      // First poll after load: adopt silently. Cost: a job that ENDED while
      // the page was closed is not announced. Lesser evil vs re-announcing
      // every running job as "Started" on every reload. info rides along so
      // a later disappearance still announces a labeled terminal.
      jobs.forEach(function (job) {
        seen[job.key] = { status: job.status, ms: -1, info: job };
      });
      primed = true;
      return;
    }

    // Bookkeeping runs OUTSIDE the gate so owner/verbosity flips can never
    // burst stale announcements later.
    var announcements = [];
    Object.keys(seen).forEach(function (key) {
      var prev = seen[key];
      if (!(key in current) && (prev.status === "running" || prev.status === "paused")) {
        var info = prev.info || {};
        var word = words[info.word_key] || "finished";
        var tail = (word === "failed" || word === "error")
          ? failedTail(errors, info) : "";
        announcements.push(["terminal", jobLabel(info) + " " + word, tail]);
        delete seen[key];  // announce ONCE, then forget
      }
    });
    jobs.forEach(function (job) {
      var prev = seen[job.key];
      if (!prev) {
        announcements.push(["start", "Started " + jobLabel(job)]);
        seen[job.key] = { status: job.status, ms: -1, info: job };
      } else {
        if (prev.status === "running" && job.status !== "running" &&
            TERMINAL.indexOf(job.status) !== -1) {
          // only REAL terminal words (a "cancelling" status is not terminal —
          // the final word arrives via the disappearance branch or stays silent,
          // matching applio_a11y's LIVE/TERMINAL partition on the native side)
          var tail = (job.status === "failed" || job.status === "error")
            ? failedTail(errors, job) : "";
          announcements.push(["terminal", jobLabel(job) + " " + job.status, tail]);
        }
        if (verbosity === "verbose" && typeof job.pct === "number" &&
            job.status === "running") {
          var highest = -1;
          MILESTONES.forEach(function (ms) {
            if (job.pct >= ms && prev.ms < ms && ms > highest) { highest = ms; }
          });
          if (highest > 0) {
            announcements.push(["milestone", jobLabel(job) + " " + highest + "%"]);
            prev.ms = highest;
          }
        }
        prev.status = job.status;
        prev.info = job;
      }
    });
    // Drop terminal keys that vanished earlier (already deleted above);
    // nothing else to clean.

    // Terminal results persist to the visible Last-result region for EVERY
    // client (visual, not spoken — no doubling with native announcements);
    // the spoken live-region announcements run only for web-owner clients.
    announcements.forEach(function (a) {
      if (a[0] === "terminal") {
        persistResult(a[2] ? a[1] + " — " + a[2] : a[1]);
      }
    });
    if (owner === "web" && verbosity !== "off") {
      // ONE announce per poll: the live region is a single text node, so
      // per-event calls in the same poll overwrite each other — only the
      // last was heard (re-test round 2). Join everything this poll made.
      var spoken = [];
      announcements.forEach(function (a) { spoken.push(a[1]); });
      if (spoken.length) {
        announce(spoken.join(" — "));
      }
    }
  }

  function poll() {
    var qs = [];
    if (lastNav) { qs.push("nav=" + encodeURIComponent(lastNav)); }
    qs.push("client=" + (window.pywebview ? "native" : "web"));
    var url = "/applio-a11y/progress" + (qs.length ? "?" + qs.join("&") : "");
    fetch(url, { credentials: "same-origin" })
      .then(function (r) { if (!r.ok) { throw new Error(String(r.status)); } return r.json(); })
      .then(function (payload) { pollFailures = 0; handlePayload(payload); })
      .catch(function () { pollFailures += 1; })
      .finally(function () {
        ensureRegions();
        window.setTimeout(poll, pollFailures > 2 ? BACKOFF_MS : POLL_MS);
      });
  }

  /* --- boot ------------------------------------------------------------- */

  function boot() {
    ensureRegions();
    healAccordions(); healRecordToggles(); healImageAlts(); readNav();
    observeToasts();
    var mo = new MutationObserver(scheduleHeal);
    mo.observe(document.body, { childList: true, subtree: true });
    poll();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
