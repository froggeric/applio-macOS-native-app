#!/bin/bash
#
# sign_bundle.sh - Deep-sign a PyInstaller macOS app bundle for notarization
#
# Usage: ./sign_bundle.sh [options] /path/to/App.app
#
# This script handles the complex signing requirements for PyInstaller bundles:
# 1. Signs all embedded binaries (.dylib, .so, Mach-O files) from inside-out
# 2. Applies Hardened Runtime to all code
# 3. Applies entitlements to the main bundle
# 4. Verifies the final signature
#
# Prerequisites:
#   - Xcode Command Line Tools (codesign, security)
#   - Valid "Developer ID Application" certificate in keychain
#

set -euo pipefail

# =============================================================================
# Configuration
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENTITLEMENTS_FILE="${SCRIPT_DIR}/entitlements_dev_id.plist"
SIGN_OPTIONS="--options runtime --timestamp"
VERBOSE=0
DRY_RUN=0
IDENTITY=""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# =============================================================================
# Helper Functions
# =============================================================================

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
}

log_debug() {
    if [[ $VERBOSE -eq 1 ]]; then
        echo -e "${BLUE}[DEBUG]${NC} $1"
    fi
}

usage() {
    cat << EOF
Usage: $(basename "$0") [options] /path/to/App.app

Deep-sign a PyInstaller macOS app bundle for notarization.

Options:
    -i, --identity IDENTITY    Signing identity (default: auto-detect Developer ID)
    -e, --entitlements FILE    Path to entitlements file
                               (default: scripts/entitlements_dev_id.plist)
    -v, --verbose              Enable verbose output
    -n, --dry-run              Show what would be done without signing
    -h, --help                 Show this help message

Examples:
    # Auto-detect identity and sign
    $(basename "$0") dist/Applio.app

    # Specify identity explicitly
    $(basename "$0") -i "Developer ID Application: Your Name (TEAMID)" dist/Applio.app

    # Dry run to see what would be signed
    $(basename "$0") --dry-run dist/Applio.app

Prerequisites:
    1. Valid "Developer ID Application" certificate in your keychain
    2. Run 'security find-identity -v -p codesigning' to list available identities
EOF
    exit 0
}

# =============================================================================
# Auto-detect Developer ID Application certificate
# =============================================================================
detect_identity() {
    log_info "Auto-detecting Developer ID Application certificate..."

    local identities
    identities=$(security find-identity -v -p codesigning 2>/dev/null | grep "Developer ID Application" || true)

    if [[ -z "$identities" ]]; then
        log_error "No 'Developer ID Application' certificate found in keychain."
        log_error "Available signing identities:"
        security find-identity -v -p codesigning >&2 || true
        exit 1
    fi

    # Count matches
    local count
    count=$(echo "$identities" | wc -l | tr -d ' ')

    if [[ $count -gt 1 ]]; then
        log_warning "Multiple Developer ID Application certificates found:"
        echo "$identities" | while read -r line; do
            echo "  $line"
        done
        log_error "Please specify identity with -i option."
        exit 1
    fi

    # Extract the identity (format: "1) HASH "Developer ID Application: Name (TEAMID)"")
    IDENTITY=$(echo "$identities" | sed -n 's/.*"\(Developer ID Application[^"]*\)".*/\1/p')

    if [[ -z "$IDENTITY" ]]; then
        log_error "Failed to parse identity from: $identities"
        exit 1
    fi

    log_success "Found identity: $IDENTITY"
}

# =============================================================================
# Get directory depth (for sorting deepest-first)
# =============================================================================
get_depth() {
    local path="$1"
    # Count slashes to determine depth
    echo "$path" | tr -cd '/' | wc -c
}

# =============================================================================
# Find all binaries that need signing
# =============================================================================
find_binaries() {
    local app_path="$1"
    local contents_path="${app_path}/Contents"

    local binaries=()

    # Find .so files
    while IFS= read -r -d '' file; do
        binaries+=("$file")
    done < <(find "$contents_path" -name "*.so" -type f -print0 2>/dev/null || true)

    # Find .dylib files
    while IFS= read -r -d '' file; do
        binaries+=("$file")
    done < <(find "$contents_path" -name "*.dylib" -type f -print0 2>/dev/null || true)

    # Find framework binaries (inside *.framework/Versions/*/ *)
    while IFS= read -r -d '' file; do
        # Skip symlinks and directories
        if [[ -f "$file" && ! -L "$file" ]]; then
            binaries+=("$file")
        fi
    done < <(find "$contents_path/Frameworks" -path "*.framework/Versions/*" -type f -print0 2>/dev/null || true)

    # Find main executable
    local main_exec="${contents_path}/MacOS"
    if [[ -d "$main_exec" ]]; then
        while IFS= read -r -d '' file; do
            if [[ -f "$file" && ! -L "$file" ]]; then
                binaries+=("$file")
            fi
        done < <(find "$main_exec" -type f -print0 2>/dev/null || true)
    fi

    # Output sorted by depth (deepest first)
    for binary in "${binaries[@]}"; do
        echo "$(get_depth "$binary") $binary"
    done | sort -rn | cut -d' ' -f2-
}

# =============================================================================
# Check if file is a Mach-O binary
# =============================================================================
is_macho() {
    local file="$1"

    # Use file command to check
    local file_type
    file_type=$(file -b "$file" 2>/dev/null || echo "")

    [[ "$file_type" == *"Mach-O"* ]]
}

# =============================================================================
# Sign a single binary
# =============================================================================
sign_binary() {
    local binary="$1"
    local sign_cmd=("codesign" "--force" "--sign" "$IDENTITY" $SIGN_OPTIONS "$binary")

    if [[ $DRY_RUN -eq 1 ]]; then
        log_info "[DRY RUN] Would sign: $binary"
        return 0
    fi

    log_debug "Signing: $binary"

    if ! "${sign_cmd[@]}" 2>&1; then
        log_error "Failed to sign: $binary"
        return 1
    fi

    return 0
}

# =============================================================================
# Sign the main app bundle
# =============================================================================
sign_app_bundle() {
    local app_path="$1"
    local sign_cmd=("codesign" "--force" "--deep" "--sign" "$IDENTITY"
                    "--entitlements" "$ENTITLEMENTS_FILE"
                    $SIGN_OPTIONS "$app_path")

    if [[ $DRY_RUN -eq 1 ]]; then
        log_info "[DRY RUN] Would sign bundle with entitlements: $app_path"
        return 0
    fi

    log_info "Signing app bundle with entitlements..."

    if ! "${sign_cmd[@]}" 2>&1; then
        log_error "Failed to sign app bundle"
        return 1
    fi

    return 0
}

# =============================================================================
# Remove existing signatures (ad-hoc or otherwise)
# =============================================================================
remove_signatures() {
    local app_path="$1"

    if [[ $DRY_RUN -eq 1 ]]; then
        log_info "[DRY RUN] Would remove existing signatures from: $app_path"
        return 0
    fi

    log_info "Removing existing signatures..."

    # Remove signature from app bundle
    codesign --remove-signature "$app_path" 2>/dev/null || true

    # Remove signatures from all binaries
    while IFS= read -r binary; do
        if [[ -n "$binary" ]] && is_macho "$binary"; then
            codesign --remove-signature "$binary" 2>/dev/null || true
        fi
    done < <(find_binaries "$app_path")
}

# =============================================================================
# Verify the final signature
# =============================================================================
verify_signature() {
    local app_path="$1"

    if [[ $DRY_RUN -eq 1 ]]; then
        log_info "[DRY RUN] Would verify signature of: $app_path"
        return 0
    fi

    log_info "Verifying signature..."

    # Detailed verification
    if ! codesign -dvvv "$app_path" 2>&1; then
        log_error "Signature verification failed"
        return 1
    fi

    # Check entitlements were applied
    log_info "Verifying entitlements..."
    if ! codesign -d --entitlements - "$app_path" 2>&1 | head -50; then
        log_error "Failed to read entitlements"
        return 1
    fi

    # Gatekeeper assessment
    log_info "Running Gatekeeper assessment..."
    if ! spctl --assess --verbose=4 --type execute "$app_path" 2>&1; then
        log_warning "Gatekeeper assessment failed (this may be expected for some PyInstaller apps)"
        log_warning "The app should still notarize correctly if the signature is valid."
    fi

    log_success "Signature verification complete"
    return 0
}

# =============================================================================
# Main
# =============================================================================
main() {
    local app_path=""

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -i|--identity)
                IDENTITY="$2"
                shift 2
                ;;
            -e|--entitlements)
                ENTITLEMENTS_FILE="$2"
                shift 2
                ;;
            -v|--verbose)
                VERBOSE=1
                shift
                ;;
            -n|--dry-run)
                DRY_RUN=1
                shift
                ;;
            -h|--help)
                usage
                ;;
            -*)
                log_error "Unknown option: $1"
                usage
                ;;
            *)
                app_path="$1"
                shift
                ;;
        esac
    done

    # Validate app path
    if [[ -z "$app_path" ]]; then
        log_error "No app path specified"
        usage
    fi

    if [[ ! -d "$app_path" ]]; then
        log_error "App not found: $app_path"
        exit 1
    fi

    if [[ ! "$app_path" == *.app ]]; then
        log_error "Path must be an .app bundle: $app_path"
        exit 1
    fi

    # Validate entitlements file
    if [[ ! -f "$ENTITLEMENTS_FILE" ]]; then
        log_error "Entitlements file not found: $ENTITLEMENTS_FILE"
        exit 1
    fi

    # Auto-detect identity if not specified
    if [[ -z "$IDENTITY" ]]; then
        detect_identity
    fi

    log_info "============================================"
    log_info "Signing PyInstaller App Bundle"
    log_info "============================================"
    log_info "App: $app_path"
    log_info "Identity: $IDENTITY"
    log_info "Entitlements: $ENTITLEMENTS_FILE"
    log_info "============================================"

    # Step 1: Remove existing signatures
    remove_signatures "$app_path"

    # Step 2: Find and sign all binaries (deepest first)
    log_info "Signing embedded binaries..."

    local binary_count=0
    local failed_count=0

    while IFS= read -r binary; do
        if [[ -n "$binary" ]]; then
            if is_macho "$binary"; then
                if ! sign_binary "$binary"; then
                    ((failed_count++))
                fi
                ((binary_count++))

                # Progress indicator
                if [[ $((binary_count % 50)) -eq 0 ]]; then
                    log_info "Signed $binary_count binaries..."
                fi
            fi
        fi
    done < <(find_binaries "$app_path")

    log_info "Signed $binary_count binaries ($failed_count failures)"

    if [[ $failed_count -gt 0 ]]; then
        log_error "Some binaries failed to sign. Aborting."
        exit 1
    fi

    # Step 3: Sign the main app bundle with entitlements
    if ! sign_app_bundle "$app_path"; then
        exit 1
    fi

    # Step 4: Verify the signature
    if ! verify_signature "$app_path"; then
        exit 1
    fi

    log_success "============================================"
    log_success "Signing complete!"
    log_success "============================================"
    log_info "Next step: Run notarize.sh to notarize the app"
}

main "$@"
