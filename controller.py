"""Foreground policy ownership and cleanup, independent of GUI/native APIs."""
from dataclasses import dataclass
import ntpath


def key(path):
    return ntpath.normcase(ntpath.normpath(path))


def foreground_request(foreground, *, enabled, closing, automatic, apps,
                       excluded_pids, windows_root, value):
    """Choose the focused target without broadening system-process exclusions."""
    if not enabled or closing or not foreground:
        return None
    pid, path = foreground
    if pid in excluded_pids or not ntpath.isabs(path) or not path.lower().endswith(".exe"):
        return None
    normalized = key(path)
    if normalized.startswith(key(windows_root).rstrip("\\") + "\\"):
        return None
    if automatic or normalized in {key(item) for item in apps}:
        return pid, path, value
    return None


@dataclass
class Active:
    pid: int
    path: str
    handle: object
    value: int


class Controller:
    def __init__(self, backend, log):
        self.backend, self.log = backend, log
        self.active = None
        self.blocked = None
        self.block_reason = ""

    def release(self):
        item = self.active
        if item is None:
            return True
        try:
            if not self.backend.alive(item.handle):
                # Never unregister a recycled PID using an exited process.
                self.log(f"{ntpath.basename(item.path)} exited; Windows owns termination cleanup.")
            else:
                status = self.backend.unregister(item.handle)
                if status < 0 and status & 0xFFFFFFFF != 0xC0000225:
                    self.log(f"Cleanup pending: 0x{status & 0xFFFFFFFF:08X}")
                    return False
                self.log(f"Registration removed: {ntpath.basename(item.path)}.")
            self.backend.close(item.handle)
            self.active = None
            return True
        except OSError as error:
            self.log(f"Cleanup pending: {error}")
            return False

    def step(self, desired):
        """desired is (pid,path,value) or None; only accepted entries are owned."""
        identity = (desired[0], key(desired[1]), desired[2]) if desired else None
        if identity != self.blocked:
            self.blocked, self.block_reason = None, ""
        if self.active:
            current = (self.active.pid, key(self.active.path), self.active.value)
            if current != identity or not self.backend.alive(self.active.handle):
                if not self.release():
                    return "Cleanup pending — retrying before another activation"
        if desired is None:
            return "Waiting for app"
        if self.active:
            return f"Registered: {ntpath.basename(self.active.path)} · yield {self.active.value}%"
        if self.blocked == identity:
            return self.block_reason
        pid, path, value = desired
        handle = None
        try:
            handle = self.backend.open(pid)
            if key(self.backend.path(handle)) != key(path) or not self.backend.alive(handle):
                return "App changed while opening — waiting"
            status = self.backend.register(handle, value)
            if status < 0:
                if status & 0xFFFFFFFF == 0xC0000718:
                    reason = "App already registered by Windows or another controller"
                else:
                    reason = f"Registration unavailable: 0x{status & 0xFFFFFFFF:08X}"
                self.blocked, self.block_reason = identity, reason
                self.log(f"{ntpath.basename(path)}: {reason}")
                return reason
            self.active = Active(pid, path, handle, value)
            handle = None
            self.log(f"Accepted: {ntpath.basename(path)} · yield {value}%.")
            return f"Registered: {ntpath.basename(path)} · yield {value}%"
        except OSError as error:
            self.blocked = identity
            self.block_reason = f"Cannot register app: {error}"
            self.log(self.block_reason)
            return self.block_reason
        finally:
            if handle is not None:
                self.backend.close(handle)

    def retry(self):
        self.blocked, self.block_reason = None, ""
