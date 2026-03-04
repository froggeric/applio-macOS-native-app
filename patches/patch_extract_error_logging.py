#!/usr/bin/env python3
"""
Patcher to add file-based error logging to F0 extraction.

Bug: Exception handling in extract.py just prints to stdout, which gets
lost in multiprocessing spawn mode. Errors are silently swallowed.

Fix: Add file-based logging so extraction errors are persisted and can
be diagnosed after the fact.

Applied at build time by build_macos.py.
"""

import os
import re


def patch_extract_py(base_path: str) -> bool:
    """Patch rvc/train/extract/extract.py to log errors to file."""
    extract_py_path = os.path.join(base_path, "extract.py")

    if not os.path.exists(extract_py_path):
        print(f"[patch_extract_error_logging] extract.py not found at {extract_py_path}")
        return False

    with open(extract_py_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Idempotency check
    if "_EXTRACT_ERROR_LOGGING_PATCHED" in content:
        print(f"[patch_extract_error_logging] extract.py already patched")
        return True

    patched = False

    # Pattern: The silent exception handler
    # Original:
    #     except Exception as error:
    #         print(
    #             f"An error occurred extracting file {inp_path} on {self.device}: {error}"
    #         )
    #
    # Patched: Add file-based logging before the print

    old_pattern = r'''except Exception as error:
            print\(
                f"An error occurred extracting file \{inp_path\} on \{self\.device\}: \{error\}"
            \)'''

    new_code = '''except Exception as error:
            # Log to file for debugging (persists across multiprocessing spawn)
            import datetime
            error_log_path = os.path.expanduser("~/Library/Logs/Applio/extraction_errors.log")
            try:
                os.makedirs(os.path.dirname(error_log_path), exist_ok=True)
                with open(error_log_path, "a") as error_log:
                    error_log.write(f"[{datetime.datetime.now().isoformat()}] {inp_path}: {error}" + chr(10))
            except IOError:
                pass  # Can't log if logging fails
            print(
                f"An error occurred extracting file {inp_path} on {self.device}: {error}"
            )'''

    if re.search(old_pattern, content):
        content = re.sub(old_pattern, new_code, content)
        print(f"[patch_extract_error_logging] Added file-based error logging")
        patched = True

    if patched:
        # Add idempotency marker
        content = "# _EXTRACT_ERROR_LOGGING_PATCHED = True\n" + content

        with open(extract_py_path, "w", encoding="utf-8") as f:
            f.write(content)
        return True

    print(f"[patch_extract_error_logging] No patterns found in extract.py")
    return False


if __name__ == "__main__":
    import sys
    base_path = sys.argv[1] if len(sys.argv) > 1 else "."
    success = patch_extract_py(base_path)
    sys.exit(0 if success else 1)
