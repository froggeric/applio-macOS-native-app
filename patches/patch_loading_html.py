#!/usr/bin/env python3
"""
Patcher to update assets/loading.html with the actual build version.

Replaces placeholder version pattern (e.g., "v3.6.0.3") with the VERSION
from build_macos.py, ensuring the loading screen displays the correct version.

Applied at build time by build_macos.py.
"""

import os
import re
import sys


def get_version_from_build_script() -> str:
    """
    Extract VERSION from build_macos.py.

    Returns:
        Version string (e.g., "3.6.0.3") or "3.6.0.3" as fallback
    """
    # Find build_macos.py - check common locations
    possible_paths = [
        "build_macos.py",
        os.path.join(os.path.dirname(__file__), "..", "build_macos.py"),
    ]

    for build_script_path in possible_paths:
        if os.path.exists(build_script_path):
            try:
                with open(build_script_path, "r", encoding="utf-8") as f:
                    content = f.read()

                # Look for VERSION = f"{APPLIO_VERSION}.{BUILD_NUMBER}"
                # or VERSION = f"{APPLIO_VERSION}.{args.build_number}"
                # First try to get APPLIO_VERSION and BUILD_NUMBER

                # Extract APPLIO_VERSION (from get_applio_version() or direct assignment)
                applio_match = re.search(
                    r'APPLIO_VERSION\s*=\s*get_applio_version\(\)',
                    content
                )
                if not applio_match:
                    applio_match = re.search(
                        r'APPLIO_VERSION\s*=\s*["\']([^"\']+)["\']',
                        content
                    )

                # Extract BUILD_NUMBER
                build_match = re.search(
                    r'BUILD_NUMBER\s*=\s*(\d+)',
                    content
                )

                if applio_match and build_match:
                    # Get APPLIO_VERSION from assets/config.json
                    config_path = "assets/config.json"
                    if os.path.exists(config_path):
                        import json
                        try:
                            with open(config_path, "r") as f:
                                config = json.load(f)
                                applio_version = config.get("version", "3.6.0")
                        except:
                            applio_version = "3.6.0"
                    else:
                        applio_version = "3.6.0"

                    build_number = build_match.group(1)
                    return f"{applio_version}.{build_number}"

                # Fallback: look for VERSION = "x.y.z.w" pattern
                version_match = re.search(
                    r'VERSION\s*=\s*f?["\']?([\d.]+)["\']?',
                    content
                )
                if version_match:
                    return version_match.group(1)

            except Exception as e:
                print(f"[patch_loading_html] Warning: Could not read build script: {e}")

    # Fallback version
    print("[patch_loading_html] Warning: Could not extract version from build_macos.py, using fallback")
    return "3.6.0.3"


def patch_loading_html(file_path: str) -> bool:
    """
    Patch assets/loading.html to replace placeholder version with actual version.

    Args:
        file_path: Path to assets/loading.html

    Returns:
        True if patching succeeded, False otherwise
    """
    if not os.path.exists(file_path):
        print(f"[patch_loading_html] Error: {file_path} not found")
        return False

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Get the actual version
    version = get_version_from_build_script()
    print(f"[patch_loading_html] Using version: {version}")

    # Pattern to match version in the footer
    # Matches: Applio v3.6.0.3 or v3.6.0.3 or similar patterns
    version_pattern = r'(id="version-line"[^>]*>Applio\s+v)[\d.]+(\s*\|\s*METAL\s+ACCELERATED)'

    if re.search(version_pattern, content):
        new_content = re.sub(
            version_pattern,
            rf'\g<1>{version}\g<2>',
            content
        )

        if new_content != content:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            print(f"[patch_loading_html] Updated version to v{version}")
            return True
        else:
            print(f"[patch_loading_html] Version already set to v{version}")
            return True
    else:
        # Try alternative pattern for single-line footer (legacy format)
        legacy_pattern = r'(<div class="footer">ENGINE\s+v)[\d.]+(\s*\|\s*METAL\s+ACCELERATED</div>)'

        if re.search(legacy_pattern, content):
            print("[patch_loading_html] Found legacy footer format, updating...")
            new_content = re.sub(
                legacy_pattern,
                rf'''<div class="footer">
        <span id="version-line">Applio v{version} | METAL ACCELERATED</span><br>
        <span style="font-size: 8px; opacity: 0.7;">© 2026 Frédéric Guigand</span>
    </div>''',
                content
            )

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            print(f"[patch_loading_html] Updated legacy footer to v{version}")
            return True

        print("[patch_loading_html] Warning: Version pattern not found in loading.html")
        return False


def patch_all(base_path: str) -> bool:
    """
    Apply loading.html patch.

    Args:
        base_path: Path to the assets directory or project root

    Returns:
        True if patching succeeded, False otherwise
    """
    # Determine the file path
    if os.path.basename(base_path) == "assets":
        file_path = os.path.join(base_path, "loading.html")
    else:
        file_path = os.path.join(base_path, "assets", "loading.html")

    print(f"[patch_loading_html] Patching {file_path}")

    return patch_loading_html(file_path)


if __name__ == "__main__":
    # Accept either the assets directory or the project root
    base_path = sys.argv[1] if len(sys.argv) > 1 else "."

    success = patch_all(base_path)
    sys.exit(0 if success else 1)
