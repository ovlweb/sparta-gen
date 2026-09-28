"""ffmpeg as a function of this process — for where apps cannot start programs (iOS).

The engine builds ffmpeg command lines and runs them as programs (:mod:`spartagen.ffmpeg`).  On iOS ffmpeg is
FFmpegKit — ffmpeg compiled into the app, one command line per call — so the same command lines run through a
function instead: ``call(argv, log_path) -> exit code`` runs one (``argv[0]`` is ``"ffmpeg"``) and writes
everything ffmpeg printed to ``log_path``.  What a program reads from stdin or writes to stdout goes through
files: ``pipe:1`` output into a temporary file, ``pipe:0`` input (the video encoder's frames) through a named pipe.
The call must let other Python threads run while ffmpeg works (a ctypes function does).
"""

from __future__ import annotations

import errno
import os
import shutil
import tempfile
import threading
import time
from typing import Callable, Optional

Call = Callable[[list, str], int]


class FFmpegFunction:
    def __init__(self, call: Call):
        self._call = call

    def run(self, cmd: list, input_bytes: Optional[bytes] = None) -> tuple:
        """Run a command line to its end: (exit code, what it wrote to pipe:1 — or, without that, everything it
        printed —, everything it printed)."""
        if input_bytes is not None:
            raise ValueError("ffmpeg as a function takes no input bytes")
        work = tempfile.mkdtemp(prefix="sg-ffmpeg-")
        try:
            out = os.path.join(work, "out")
            log = os.path.join(work, "log.txt")
            code = _call(self._call, [out if a == "pipe:1" else a for a in cmd], log)
            printed = _read(log)
            return code, (_read(out) if "pipe:1" in cmd else printed), printed
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def popen(self, cmd: list) -> "Process":
        """Start a command line that reads ``pipe:0``: what :class:`spartagen.ffmpeg.VideoWriter` uses of a
        subprocess.Popen (``stdin``, ``stderr``, ``wait``)."""
        return Process(self._call, cmd)


class Process:
    def __init__(self, call: Call, cmd: list):
        self._work = tempfile.mkdtemp(prefix="sg-ffmpeg-")
        fifo = os.path.join(self._work, "in")
        os.mkfifo(fifo)
        self._log = os.path.join(self._work, "log.txt")
        self._printed = b""
        self._done = threading.Event()
        self.returncode: Optional[int] = None
        self.stdin = PipeWriter(fifo, self._done)
        self.stderr = _Printed(self)
        self._thread = threading.Thread(target=self._run, args=(call, [fifo if a == "pipe:0" else a for a in cmd]),
                                        name="ffmpeg", daemon=True)
        self._thread.start()

    def _run(self, call: Call, args: list) -> None:
        try:
            self.returncode = _call(call, args, self._log)
        finally:
            self._printed = _read(self._log)
            self._done.set()

    def wait(self) -> int:
        self._thread.join()
        shutil.rmtree(self._work, ignore_errors=True)
        return int(self.returncode if self.returncode is not None else -1)


class PipeWriter:
    """The write end of ffmpeg's input pipe.  Opened at the first write: a named pipe opens once its reader has
    it open, so this waits for ffmpeg — and if ffmpeg stops without reading, writing is a broken pipe, as with
    a program."""

    def __init__(self, path: str, done: threading.Event):
        self._path, self._done = path, done
        self._fd: Optional[int] = None
        self.closed = False

    def _open(self) -> int:
        while True:
            try:
                fd = os.open(self._path, os.O_WRONLY | os.O_NONBLOCK)
            except OSError as exc:
                if exc.errno != errno.ENXIO:           # ENXIO: nobody reads it yet
                    raise
            else:
                os.set_blocking(fd, True)
                return fd
            if self._done.is_set():
                raise BrokenPipeError(errno.EPIPE, "ffmpeg stopped before reading its input")
            time.sleep(0.005)

    def write(self, data: bytes) -> None:
        if self.closed:
            raise ValueError("write to a closed pipe")
        if self._fd is None:
            self._fd = self._open()
        view = memoryview(data)
        while view:
            view = view[os.write(self._fd, view):]

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self._fd is None:                           # nothing written: ffmpeg still waits for the pipe to open
            try:
                self._fd = self._open()
            except BrokenPipeError:
                return
        os.close(self._fd)
        self._fd = None


class _Printed:
    """ffmpeg's stderr: everything it printed, once it has finished."""

    def __init__(self, proc: Process):
        self._proc = proc
        self._pos = 0

    def read(self, n: int = -1) -> bytes:
        self._proc._done.wait()
        data = self._proc._printed
        end = len(data) if n < 0 else self._pos + n
        chunk = data[self._pos:end]
        self._pos += len(chunk)
        return chunk


def _call(call: Call, args: list, log: str) -> int:
    try:
        return int(call(args, log))
    except Exception as exc:                           # the call itself failed: say why, like ffmpeg would
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(f"\n{type(exc).__name__}: {exc}\n")
        return -1


def _read(path: str) -> bytes:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return b""
