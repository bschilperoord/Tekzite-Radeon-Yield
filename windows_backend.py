"""Version-pinned Windows broker backend; no service impersonation."""
import ctypes as C
import os
from pathlib import Path
from broker_contract import ResourceRequest, fields, validate_files


class Backend:
    def __init__(self):
        if os.name != "nt" or C.sizeof(C.c_void_p) != 8:
            raise OSError("Use 64-bit Python on Windows 11.")
        self.k = C.WinDLL("kernel32", use_last_error=True)
        self.u = C.WinDLL("user32", use_last_error=True)
        self.psapi = C.WinDLL("psapi", use_last_error=True)
        P, U = C.c_void_p, C.c_uint32
        signatures = [
            (self.k.OpenProcess, [U, C.c_int, U], P),
            (self.k.CloseHandle, [P], C.c_int),
            (self.k.WaitForSingleObject, [P, U], U),
            (self.k.QueryFullProcessImageNameW, [P, U, C.c_wchar_p, C.POINTER(U)], C.c_int),
            (self.k.GetSystemDirectoryW, [C.c_wchar_p, U], U),
            (self.k.CreateMutexW, [P, C.c_int, C.c_wchar_p], P),
            (self.u.GetForegroundWindow, [], P),
            (self.u.GetWindowThreadProcessId, [P, C.POINTER(U)], U),
            (self.psapi.EnumProcesses, [C.POINTER(U), U, C.POINTER(U)], C.c_int),
        ]
        for function, args, result in signatures:
            function.argtypes, function.restype = args, result
        self.mutex = self.k.CreateMutexW(None, False, "Local\\TekziteRadeonYield-v1")
        if not self.mutex:
            raise C.WinError(C.get_last_error())
        if C.get_last_error() == 183:
            self.close(self.mutex)
            self.mutex = None
            raise OSError("Tekzite Radeon Yield is already running.")
        try:
            buffer = C.create_unicode_buffer(32768)
            size = self.k.GetSystemDirectoryW(buffer, len(buffer))
            if not 0 < size < len(buffer):
                raise OSError("Cannot find the Windows system directory.")
            self.system32 = Path(buffer.value)
            validate_files(self.system32)
            self.lib = C.WinDLL(str(self.system32 / "rmclient.dll"), winmode=0x800)
            self.initialize = self.lib.RmGameModeInitializeResourceRequest
            self.initialize.argtypes, self.initialize.restype = [C.POINTER(ResourceRequest)], C.c_int32
            self.reg = self.lib.RmGameModeRegisterProcess
            self.reg.argtypes = [P, C.POINTER(ResourceRequest), U]
            self.reg.restype = C.c_int32
            self.unreg = self.lib.RmGameModeUnregisterProcess
            self.unreg.argtypes, self.unreg.restype = [P], C.c_int32
            self.request(5)  # Validate initializer before enabling the UI.
        except BaseException:
            self.shutdown()
            raise

    def request(self, value):
        if type(value) is not int or not 2 <= value <= 10:
            raise ValueError("GPU yield must be 2 through 10.")
        result = ResourceRequest()
        self.initialize(C.byref(result))
        expected = {"version": 6, "cpu_count": 0, "cpu_mask": "0x0", "gpu_yield": 10,
                    "game_memory_budget": 50, "dwm_memory_budget": 30,
                    "flags_1_raw": 0, "flags_2_raw": 0, "priority_class_raw": 0}
        if fields(result) != expected:
            raise OSError("Windows' broker request layout changed. Activation is disabled.")
        result.gpu_yield = value
        return result

    def open(self, pid, writable=True):
        rights = 0x101200 if writable else 0x1000
        handle = self.k.OpenProcess(rights, False, pid)
        if not handle:
            raise C.WinError(C.get_last_error())
        return handle

    def close(self, handle):
        if handle:
            self.k.CloseHandle(handle)

    def path(self, handle):
        buffer = C.create_unicode_buffer(32768)
        size = C.c_uint32(len(buffer))
        if not self.k.QueryFullProcessImageNameW(handle, 0, buffer, C.byref(size)):
            raise C.WinError(C.get_last_error())
        return buffer.value

    def alive(self, handle):
        result = self.k.WaitForSingleObject(handle, 0)
        if result == 0xFFFFFFFF:
            raise C.WinError(C.get_last_error())
        return result == 0x102

    def foreground(self):
        pid = C.c_uint32()
        self.u.GetWindowThreadProcessId(self.u.GetForegroundWindow(), C.byref(pid))
        if not pid.value:
            return None
        handle = None
        try:
            handle = self.open(pid.value, writable=False)
            return pid.value, self.path(handle)
        except OSError:
            return None
        finally:
            self.close(handle)

    def processes(self):
        capacity = 1024
        while True:
            buffer = (C.c_uint32 * capacity)()
            used = C.c_uint32()
            if not self.psapi.EnumProcesses(buffer, C.sizeof(buffer), C.byref(used)):
                raise C.WinError(C.get_last_error())
            if used.value < C.sizeof(buffer):
                break
            capacity *= 2
        results = []
        for pid in buffer[:used.value // 4]:
            if pid == os.getpid():
                continue
            handle = None
            try:
                handle = self.open(pid, writable=False)
                results.append((pid, self.path(handle)))
            except OSError:
                pass
            finally:
                self.close(handle)
        return results

    def register(self, handle, value):
        request = self.request(value)
        return self.reg(handle, C.byref(request), 0)

    def unregister(self, handle):
        return self.unreg(handle)

    def shutdown(self):
        if getattr(self, "mutex", None):
            self.close(self.mutex)
            self.mutex = None
