from __future__ import annotations

import os
import subprocess
from typing import Any, Dict


def hidden_subprocess_kwargs() -> Dict[str, Any]:
    """Return subprocess kwargs that prevent FFmpeg/FFprobe console windows on Windows.

    When the app is launched with pythonw.exe, Windows console executables such as
    ffmpeg.exe can still create a small black CMD window for every subprocess call.
    CREATE_NO_WINDOW + STARTUPINFO hides those child windows so rendering does not
    steal focus while the user is working.
    """
    if os.name != "nt":
        return {}

    kwargs: Dict[str, Any] = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    try:
        startupinfo = subprocess.STARTUPINFO()  # type: ignore[attr-defined]
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # type: ignore[attr-defined]
        startupinfo.wShowWindow = 0
        kwargs["startupinfo"] = startupinfo
    except Exception:
        # creationflags alone is usually enough. Keep this defensive so the app
        # can still run on unusual Python/Windows builds.
        pass
    return kwargs


def run_hidden(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
    kwargs.update(hidden_subprocess_kwargs())
    return subprocess.run(*args, **kwargs)


def popen_hidden(*args: Any, **kwargs: Any) -> subprocess.Popen:
    kwargs.update(hidden_subprocess_kwargs())
    return subprocess.Popen(*args, **kwargs)
