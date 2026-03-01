#!/bin/bash
#
# notarize.sh - Notarize a signed macOS app with Apple
#
# Usage: ./notarize.sh [options] /path/to/App.app
#
# This script handles the complete notarization workflow:
# 1. Creates a zip of the signed app
# 2. Submits to Apple's notarization service
# 3. Waits for completion
# 4. Staples the ticket to the app
# 5. Verifies the result
#
# Prerequisites:
#   - App must be signed with Developer ID certificate
#   - App-specific password for Apple ID (create at appleid.apple.com)
#   - Store password in keychain: xcrun notarytool store-credentials
#

set -euo pipefail

# =============================================================================
# Configuration
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERBOSE=0
APPLE_ID=""
TEAM_ID=""
PASSWORD=""
KEYCHAIN_PROFILE=""
WAIT_TIMEOUT="2h"  # Default 2 hour timeout for notarization

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

usage() {
    cat << EOF
Usage: $(basename "$0") [options] /path/to/App.app

Notarize a signed macOS app with Apple's notarization service.

Authentication Options (choose one):
    -k, --keychain-profile PROFILE  Keychain profile name (recommended)
                                           Use: xcrun notarytool store-credentials "profile-name"
    -a, --apple-id EMAIL                Apple ID email (requires --team-id and --password)
    -t, --team-id TEAM_ID               Team ID (required with --apple-id)
    -w, --password STRING               App-specific password (required with --apple-id)

Other Options:
    --timeout DURATION        Wait timeout (e.g., "30m", "2h", default: 2h)
    -v, --verbose             Enable verbose output
    -h, --help                Show this help message

Examples:
    # Using keychain profile (recommended)
    $(basename "$0") -k applio-notarize dist/Applio.app

    # Using Apple ID directly
    $(basename "$0") -a user@example.com -t TEAMID -w xxxx-xxxx-xxxx-xxxx dist/Applio.app

    # Store credentials first (one-time setup)
    xcrun notarytool store-credentials "applio-notarize" \\
        --apple-id "user@example.com" \\
        --team-id "TEAMID" \\
        --password "xxxx-xxxx-xxxx-xxxx"

Prerequisites:
    1. App must be signed with Developer ID certificate (run sign_bundle.sh first)
    2. Create app-specific password at https://appleid.apple.com
    3. Store credentials: xcrun notarytool store-credentials "profile-name"
EOF
    exit 0
}

# =============================================================================
# Check if app is signed
# =============================================================================
check_signature() {
    local app_path="$1"

    log_info "Verifying app is signed..."

    local sig_info
    sig_info=$(codesign -dvvv "$app_path" 2>&1 || true)

    if echo "$sig_info" | grep -q "Signature=adhoc"; then
        log_error "App has ad-hoc signature. Must be signed with Developer ID first."
        log_error "Run: sign_bundle.sh $app_path"
        exit 1
    fi

    if ! echo "$sig_info" | grep -q "Authority=Developer ID"; then
        log_error "App is not signed with Developer ID certificate."
        log_error "Run: sign_bundle.sh $app_path"
        exit 1
    fi

    log_success "App is properly signed with Developer ID"
}

# =============================================================================
# Create zip for notarization
# =============================================================================
create_zip() {
    local app_path="$1"
    local zip_path="$2"

    log_info "Creating zip for notarization: $zip_path"

    # Use ditto for better macOS compatibility
    ditto -c -k --keepParent "$app_path" "$zip_path"

    if [[ ! -f "$zip_path" ]]; then
        log_error "Failed to create zip file"
        exit 1
    fi

    local zip_size
    zip_size=$(du -h "$zip_path" | cut -f1)
    log_success "Created zip: $zip_path ($zip_size)"
}

# =============================================================================
# Submit for notarization
# =============================================================================
submit_notarization() {
    local zip_path="$1"
    local submit_output

    log_info "Submitting for notarization..."
    log_info "This may take several minutes..."

    local notary_cmd=("xcrun" "notarytool" "submit" "$zip_path" "--wait" "--timeout" "$WAIT_TIMEOUT")

    # Add authentication
    if [[ -n "$KEYCHAIN_PROFILE" ]]; then
        notary_cmd+=("--keychain-profile" "$KEYCHAIN_PROFILE")
    else
        notary_cmd+=("--apple-id" "$APPLE_ID" "--team-id" "$TEAM_ID" "--password" "$PASSWORD")
    fi

    # Capture output
    submit_output=$("${notary_cmd[@]}" 2>&1) || {
        log_error "Notarization submission failed"
        echo "$submit_output"
        exit 1
    }

    echo "$submit_output"

    # Check for success
    if echo "$submit_output" | grep -q "status: Accepted"; then
        log_success "Notarization successful!"
        return 0
    elif echo "$submit_output" | grep -q "status: Invalid"; then
        log_error "Notarization failed - app was rejected"
        log_error "Check the notarization log for details"

        # Try to get the log URL
        local submission_id
        submission_id=$(echo "$submit_output" | grep -oE 'id: [a-f0-9-]+' | cut -d' ' -f2 || true)

        if [[ -n "$submission_id" ]]; then
            log_error "View log: xcrun notarytool log $submission_id"
        fi

        exit 1
    else
        log_warning "Unexpected notarization result"
        return 1
    fi
}

# =============================================================================
# Staple ticket to app
# =============================================================================
staple_ticket() {
    local app_path="$1"

    log_info "Stapling notarization ticket..."

    if ! xcrun stapler staple "$app_path" 2>&1; then
        log_error "Failed to staple ticket"
        exit 1
    fi

    log_success "Ticket stapled successfully"
}

# =============================================================================
# Verify notarization
# =============================================================================
verify_notarization() {
    local app_path="$1"

    log_info "Verifying notarization..."

    # Check stapled ticket
    if ! xcrun stapler validate "$app_path" 2>&1; then
        log_error "Stapler validation failed"
        exit 1
    fi

    # Gatekeeper assessment
    log_info "Running Gatekeeper assessment..."
    if ! spctl --assess --verbose=4 --type execute "$app_path" 2>&1; then
        log_warning "Gatekeeper assessment had warnings"
    else
        log_success "Gatekeeper assessment passed"
    fi

    log_success "Notarization verified!"
}

# =============================================================================
# Cleanup temporary files
# =============================================================================
cleanup() {
    local zip_path="$1"

    if [[ -f "$zip_path" ]]; then
        log_info "Cleaning up temporary zip..."
        rm -f "$zip_path"
    fi
}

# =============================================================================
# Detect existing notarytool profile
# =============================================================================
detect_keychain_profile() {
    log_info "Checking for existing notarytool profiles..."

    # Look for keychain items stored by notarytool
    local profiles
    profiles=$(security find-generic-password -s "notarytool" 2>&1 || true)

    if [[ -z "$profiles" ]]; then
        log_error "No notarytool profiles found in keychain."
        log_error "Please create one using:"
        log_error "  xcrun notarytool store-credentials \"profile-name\" \\"
        log_error "    --apple-id \"your@email.com\" \\"
        log_error "    --team-id \"YOURTEAMID\" \\"
        log_error "    --password \"xxxx-xxxx-xxxx-xxxx\""
        exit 1
    fi

    # Use the first profile found
    KEYCHAIN_PROFILE=$(echo "$profiles" | head -1 | awk -F': \t* 1' | sed 's/[[:space:]]//')
    if [[ -z "$KEYCHAIN_PROFILE" ]]; then
        log_error "Failed to extract profile name"
        exit 1
    fi

    log_success "Using keychain profile: $KEYCHAIN_PROFILE"
}

# =============================================================================
# Main
# =============================================================================
main() {
    local app_path=""

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -k|--keychain-profile)
                KEYCHAIN_PROFILE="$2"
                shift 2
                ;;
            -a|--apple-id)
                APPLE_ID="$2"
                shift 2
                ;;
            -t|--team-id)
                TEAM_ID="$2"
                shift 2
                ;;
            -w|--password)
                PASSWORD="$2"
                shift 2
                ;;
            --timeout)
                WAIT_TIMEOUT="$2"
                shift 2
                ;;
            -v|--verbose)
                VERBOSE=1
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

    # Validate authentication
    if [[ -z "$KEYCHAIN_PROFILE" ]]; then
        detect_keychain_profile
    else
        if [[ -z "$APPLE_ID" || -z "$TEAM_ID" || -z "$PASSWORD" ]]; then
            log_error "Authentication required. Use -k for keychain profile or -a/-t/-w for credentials."
            usage
        fi
    fi

    # Resolve absolute path
    app_path="$(cd "$(dirname "$app_path")" && pwd)/$(basename "$app_path")"

    local zip_path="${app_path%.app}.zip"

    log_info "============================================"
    log_info "Notarizing macOS App"
    log_info "============================================"
    log_info "App: $app_path"
    log_info "============================================"

    # Step 1: Check signature
    check_signature "$app_path"

    # Step 2: Create zip
    create_zip "$app_path" "$zip_path"

    # Step 3: Submit for notarization (with cleanup on failure)
    if ! submit_notarization "$zip_path"; then
        cleanup "$zip_path"
        exit 1
    fi

    # Step 4: Staple ticket
    if ! staple_ticket "$app_path"; then
        cleanup "$zip_path"
        exit 1
    fi

    # Step 5: Verify
    if ! verify_notarization "$app_path"; then
        cleanup "$zip_path"
        exit 1
    fi

    # Step 6: Cleanup
    cleanup "$zip_path"

    log_success "============================================"
    log_success "Notarization complete!"
    log_success "============================================"
    log_info "The app is now ready for distribution."
    log_info ""
    log_info "To verify on another machine:"
    log_info "  spctl --assess --verbose=4 --type execute \"$app_path\""
    log_info "  xcrun stapler validate \"$app_path\""
}

main "$@"
