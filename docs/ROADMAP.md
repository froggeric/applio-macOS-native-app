# Roadmap

What is decided and what comes next for the macOS fork. The decisions are the owner's; this file records them. Newest first.

## Decisions

- **Releases are built locally (2026-11-26).** A GitHub release carries the DMG built, signed and notarized on the build Mac, tested by hand first. The two macOS workflows in `.github/workflows/` run only when started by hand (README_MACOS.md, "GitHub Actions: manual builds only"). Reasons: the published build is the one that was tested, macOS runners cost about ten times Linux minutes and were unavailable that day, and the GitHub path has not run since July 2026.

## Now

- **3.7.2.1 on upstream Applio 3.7.2.** Built, signed and notarized on 2026-11-26; `main` is pushed. It waits for the manual test pass (`TEST_PLAN_3.7.2.md`). There is no GitHub release until that pass is clean and the owner asks for it.

## Next

- **The 3.7.2.1 release:** fixes from the manual pass, a new build if anything changed, then the tag and the upload of the local DMG.
- **VoiceOver pass on the new interface.** Upstream 3.7 replaced the tabs with a sidebar and numbered steps, and added a Terminal tab. The accessibility payload was adapted (current page, blocks that render late) and checked in a browser, not with VoiceOver.
- **Realtime record Start and Stop.** The pressed state is marked only when the interface language is English, because the payload compares button text.
- **Notarization credentials.** Store a notarytool profile (`applio-notarize`, App Store Connect key) on the build Mac to return to the documented path. Until then the build uses the keychain item of that name.
- **Following upstream 3.7.x.** Procedure in CLAUDE.md, "Fork Maintenance": merge on a branch, run the tests and the patch stage, fix what `PATCH_MARKERS` reports.
- **Cleanup once 3.7.2.1 is confirmed:** the parked branches and worktree of the first 3.7.2 attempt, `venv_macos_py310`, and the temporary test data.

## Later

- **Old language files.** A data location upgraded from 3.6 keeps up to 45 language files the app no longer ships. They do no harm; a later version could remove the ones unchanged since 3.6.
- **Further upstream contributions** (the accessibility gaps listed in `ACCESSIBILITY_AUDIT.md`) wait until the manual VoiceOver pass on the current interface is clean.
- **The GitHub release workflow** (`release-macos.yml`) is kept as a fallback that has not run since 2026-07-27. Run it once from the Actions tab before relying on it, or remove it if it stays unused.
