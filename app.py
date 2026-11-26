#!/usr/bin/env python3
"""Thin launcher for the TabulaCortex Gradio app.

The original workflows load prompt templates with cwd-relative paths such as
``templates/template_extractSchema.txt``. Changing to the repository root here
keeps those paths valid no matter where the process was started from.
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

from UI_launch_log import main  # noqa: E402  (import after chdir is intentional)


if __name__ == "__main__":
    main()
