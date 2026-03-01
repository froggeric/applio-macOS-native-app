# Code Signing & Notarization Pipeline

Standalone scripts for signing and notarizing PyInstaller macOS app bundles.

## Overview

This pipeline handles the complex requirements for notarizing PyInstaller apps:
- Deep-signing all embedded binaries (`.dylib`, `.so`, Mach-O files)
- Applying Hardened Runtime with correct entitlements
- Submitting to Apple's notarization service
- Stapling the notarization ticket

## Prerequisites

### 1. Developer ID Certificate

Ensure you have a valid "Developer ID Application" certificate installed:

```bash
security find-identity -v -p codesigning
```

You should see:
```
1) ABC123... "Developer ID Application: Your Name (TEAMID)"
```

### 2. App-Specific Password (for Notarization)

1. Go to [appleid.apple.com](https://appleid.apple.com)
2. Sign in with your Apple ID
3. Under Security → App-Specific Passwords, generate a new password
4. Store it securely (you'll need it once)

### 3. Store Credentials in Keychain (Recommended)

```bash
xcrun notarytool store-credentials "applio-notarize" \
    --apple-id "your-email@example.com" \
    --team-id "YOURTEAMID" \
    --password "xxxx-xxxx-xxxx-xxxx"
```

This stores your credentials securely in the keychain. You can then use `-p applio-notarize` instead of passing credentials each time.

## Quick Start

### Sign the App

```bash
# Auto-detect identity and sign
./scripts/sign_bundle.sh dist/Applio.app

# Or specify identity explicitly
./scripts/sign_bundle.sh -i "Developer ID Application: Your Name (TEAMID)" dist/Applio.app
```

### Notarize the App

```bash
# Using keychain profile (recommended)
./scripts/notarize.sh -p "applio-notarize" dist/Applio.app

# Or pass credentials directly
./scripts/notarize.sh \
    -a "your-email@example.com" \
    -t "YOURTEAMID" \
    -w "xxxx-xxxx-xxxx-xxxx" \
    dist/Applio.app
```

### Verify the Result

```bash
# Check signature and entitlements
codesign -dvvv --entitlements - dist/Applio.app

# Gatekeeper assessment
spctl --assess --verbose=4 --type execute dist/Applio.app

# Validate stapled ticket
xcrun stapler validate dist/Applio.app
```

## Scripts

### `sign_bundle.sh`

Deep-sign a PyInstaller app bundle for notarization.

| Option | Description |
|--------|-------------|
| `-i, --identity` | Signing identity (default: auto-detect) |
| `-e, --entitlements` | Path to entitlements file |
| `-v, --verbose` | Enable verbose output |
| `-n, --dry-run` | Show what would be done without signing |

**What it does:**
1. Removes existing signatures (ad-hoc or otherwise)
2. Finds all `.dylib`, `.so`, and Mach-O binaries
3. Signs each binary with Hardened Runtime (`--options runtime`)
4. Signs the main app bundle with entitlements
5. Verifies the final signature

### `notarize.sh`

Submit a signed app to Apple's notarization service.

| Option | Description |
|--------|-------------|
| `-p, --password` | Keychain profile name (recommended) |
| `-a, --apple-id` | Apple ID email |
| `-t, --team-id` | Team ID |
| `-w, --password` | App-specific password |
| `--timeout` | Wait timeout (default: 2h) |
| `-v, --verbose` | Enable verbose output |

**What it does:**
1. Verifies the app is signed with Developer ID
2. Creates a zip of the app
3. Submits to Apple's notarization service
4. Waits for completion
5. Staples the notarization ticket
6. Verifies the result

### `entitlements_dev_id.plist`

Entitlements for Developer ID distribution. Includes:
- `com.apple.security.cs.allow-jit` — PyTorch/Python JIT compilation
- `com.apple.security.cs.allow-unsigned-executable-memory` — Dynamic library loading
- `com.apple.security.cs.disable-library-validation` — Mixed signing states
- `com.apple.security.device.audio-input` — Microphone access
- `com.apple.security.files.user-selected.read-write` — Folder picker
- `com.apple.security.network.client` — Network access

**Note:** No App Sandbox for Developer ID distribution (allows flexible data storage).

## Troubleshooting

### "signature invalid" or "signature failed to verify"

The app may have leftover ad-hoc signatures. Run:
```bash
# Remove existing signatures
codesign --remove-signature --deep dist/Applio.app

# Then re-sign
./scripts/sign_bundle.sh dist/Applio.app
```

### Notarization Failed

Check the notarization log:
```bash
# Get submission ID from notarytool output
xcrun notarytool log SUBMISSION_ID --keychain-profile "applio-notarize"
```

Common issues:
- **Missing entitlements** — Ensure microphone description is in Info.plist
- **Unsigned binaries** — Re-run `sign_bundle.sh` with `--verbose`
- **Hardened Runtime issues** — Check entitlements include JIT exemptions

### Gatekeeper Rejection After Notarization

On the target machine:
```bash
# Remove quarantine attribute (PyInstaller apps may still need this)
xattr -cr Applio.app

# Then launch
open Applio.app
```

### "The signature of the binary is invalid"

This often means a binary was missed during deep signing. Check:
```bash
# List all unsigned binaries
find dist/Applio.app/Contents -type f \( -name "*.so" -o -name "*.dylib" \) -exec sh -c '
    codesign -dv "$1" 2>&1 | grep -q "code object is not signed" && echo "$1"
' _ {} \;
```

## Mac App Store Migration (Future)

For Mac App Store distribution, the following changes are needed:

1. **Different certificate**: Use "Apple Distribution" instead of "Developer ID Application"
2. **App Sandbox**: Must be enabled with strict entitlements
3. **Hardened Runtime exemptions**: May be rejected by MAS review
4. **File access**: Must use security-scoped bookmarks

See the plan file for detailed migration strategy.

## Files

```
scripts/
├── entitlements_dev_id.plist   # Entitlements for Developer ID signing
├── sign_bundle.sh              # Deep-signing script
├── notarize.sh                 # Notarization pipeline
└── README.md                   # This file
```

## License

Part of the Applio macOS native app project.
