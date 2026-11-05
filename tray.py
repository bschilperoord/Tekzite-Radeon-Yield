"""Native Windows notification icon with a dedicated message thread."""
import ctypes as C
from ctypes import wintypes as W
from pathlib import Path
import threading


class Tray:
    def __init__(self, callback):
        self.callback = callback
        self.hwnd = None
        self.error = None
        self.available = False
        self.stopping = threading.Event()
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        if not self.ready.wait(3):
            self.stopping.set()
            self.error = "Tray initialization timed out"

    def close(self):
        self.stopping.set()
        if self.hwnd:
            self.user.PostMessageW(self.hwnd, 0x10, 0, 0)
        self.thread.join(timeout=1)

    def _run(self):
        user = self.user = C.WinDLL("user32", use_last_error=True)
        shell = C.WinDLL("shell32", use_last_error=True)
        kernel = C.WinDLL("kernel32", use_last_error=True)
        result_type = C.c_ssize_t
        proc_type = C.WINFUNCTYPE(result_type, W.HWND, W.UINT, W.WPARAM, W.LPARAM)

        class WindowClass(C.Structure):
            _fields_ = [("style", W.UINT), ("proc", proc_type), ("class_extra", C.c_int),
                        ("window_extra", C.c_int), ("instance", W.HINSTANCE),
                        ("icon", W.HICON), ("cursor", W.HANDLE), ("background", W.HBRUSH),
                        ("menu", W.LPCWSTR), ("name", W.LPCWSTR)]

        class Guid(C.Structure):
            _fields_ = [("data1", W.DWORD), ("data2", W.WORD), ("data3", W.WORD), ("data4", C.c_byte * 8)]

        class IconData(C.Structure):
            _fields_ = [("size", W.DWORD), ("window", W.HWND), ("id", W.UINT),
                        ("flags", W.UINT), ("message", W.UINT), ("icon", W.HICON),
                        ("tip", W.WCHAR * 128), ("state", W.DWORD), ("state_mask", W.DWORD),
                        ("info", W.WCHAR * 256), ("timeout", W.UINT), ("title", W.WCHAR * 64),
                        ("info_flags", W.DWORD), ("guid", Guid), ("balloon_icon", W.HICON)]

        signatures = [
            (kernel.GetModuleHandleW, [W.LPCWSTR], W.HMODULE),
            (user.RegisterClassW, [C.POINTER(WindowClass)], W.ATOM),
            (user.UnregisterClassW, [W.LPCWSTR, W.HINSTANCE], W.BOOL),
            (user.CreateWindowExW, [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD,
                                    C.c_int, C.c_int, C.c_int, C.c_int, W.HWND, W.HMENU,
                                    W.HINSTANCE, C.c_void_p], W.HWND),
            (user.DefWindowProcW, [W.HWND, W.UINT, W.WPARAM, W.LPARAM], result_type),
            (user.DestroyWindow, [W.HWND], W.BOOL),
            (user.PostQuitMessage, [C.c_int], None),
            (user.PostMessageW, [W.HWND, W.UINT, W.WPARAM, W.LPARAM], W.BOOL),
            (user.GetMessageW, [C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT], C.c_int),
            (user.TranslateMessage, [C.POINTER(W.MSG)], W.BOOL),
            (user.DispatchMessageW, [C.POINTER(W.MSG)], result_type),
            (user.LoadImageW, [W.HINSTANCE, W.LPCWSTR, W.UINT, C.c_int, C.c_int, W.UINT], W.HANDLE),
            (user.DestroyIcon, [W.HICON], W.BOOL),
            (user.RegisterWindowMessageW, [W.LPCWSTR], W.UINT),
            (user.CreatePopupMenu, [], W.HMENU),
            (user.AppendMenuW, [W.HMENU, W.UINT, C.c_size_t, W.LPCWSTR], W.BOOL),
            (user.TrackPopupMenu, [W.HMENU, W.UINT, C.c_int, C.c_int, C.c_int, W.HWND, C.c_void_p], W.UINT),
            (user.DestroyMenu, [W.HMENU], W.BOOL),
            (user.GetCursorPos, [C.POINTER(W.POINT)], W.BOOL),
            (user.SetForegroundWindow, [W.HWND], W.BOOL),
            (shell.Shell_NotifyIconW, [W.DWORD, C.POINTER(IconData)], W.BOOL),
        ]
        for function, arguments, result in signatures:
            function.argtypes, function.restype = arguments, result
        instance = kernel.GetModuleHandleW(None)
        class_name = "TekziteRadeonYieldTray"
        callback_message = 0x8001
        taskbar_created = user.RegisterWindowMessageW("TaskbarCreated")
        data = IconData()
        icon = None
        registered_class = False

        def add_icon():
            added = bool(shell.Shell_NotifyIconW(0, C.byref(data)))
            self.available = added
            return added

        def menu(hwnd):
            handle = user.CreatePopupMenu()
            if not handle:
                return
            try:
                for number, label in ((1, "Show"), (2, "Start / stop tracking"), (3, "Exit")):
                    user.AppendMenuW(handle, 0, number, label)
                point = W.POINT()
                user.GetCursorPos(C.byref(point))
                user.SetForegroundWindow(hwnd)
                choice = user.TrackPopupMenu(handle, 0x100 | 0x2, point.x, point.y, 0, hwnd, None)
                if choice:
                    self.callback({1: "show", 2: "toggle", 3: "exit"}[choice])
                user.PostMessageW(hwnd, 0, 0, 0)
            finally:
                user.DestroyMenu(handle)

        @proc_type
        def window_proc(hwnd, message, wparam, lparam):
            try:
                if message == callback_message:
                    if lparam in (0x202, 0x203):  # Left click / double click
                        self.callback("show")
                    elif lparam == 0x205:
                        menu(hwnd)
                    return 0
                if message == taskbar_created:
                    if not add_icon():
                        self.callback("tray_error")
                    return 0
                if message == 0x10:
                    user.DestroyWindow(hwnd)
                    return 0
                if message == 0x2:
                    shell.Shell_NotifyIconW(2, C.byref(data))
                    self.available = False
                    user.PostQuitMessage(0)
                    return 0
                if message == 0x11:  # Allow Windows sign-out.
                    return 1
                if message == 0x16 and wparam:
                    self.callback("exit")
                    return 0
            except Exception:
                self.callback("tray_error")
            return user.DefWindowProcW(hwnd, message, wparam, lparam)

        try:
            window_class = WindowClass()
            window_class.proc, window_class.instance, window_class.name = window_proc, instance, class_name
            if not user.RegisterClassW(C.byref(window_class)):
                raise C.WinError(C.get_last_error())
            registered_class = True
            self.hwnd = user.CreateWindowExW(0, class_name, "Radeon Yield", 0,
                                             0, 0, 0, 0, None, None, instance, None)
            if not self.hwnd:
                raise C.WinError(C.get_last_error())
            icon = user.LoadImageW(None, str(Path(__file__).with_name("tray.ico")), 1, 32, 32, 0x10)
            if not icon:
                raise C.WinError(C.get_last_error())
            data.size, data.window, data.id = C.sizeof(data), self.hwnd, 1
            data.flags, data.message, data.icon = 1 | 2 | 4, callback_message, icon
            data.tip = "Tekzite Radeon Yield"
            if not add_icon():
                raise OSError("Windows notification area unavailable")
            self.ready.set()
            if self.stopping.is_set():
                return
            message = W.MSG()
            while not self.stopping.is_set():
                result = user.GetMessageW(C.byref(message), None, 0, 0)
                if result == -1:
                    raise C.WinError(C.get_last_error())
                if result == 0:
                    break
                user.TranslateMessage(C.byref(message))
                user.DispatchMessageW(C.byref(message))
        except Exception as error:
            self.error = str(error)
            self.callback("tray_error")
        finally:
            self.available = False
            shell.Shell_NotifyIconW(2, C.byref(data))
            if self.hwnd:
                user.DestroyWindow(self.hwnd)
                self.hwnd = None
            if icon:
                user.DestroyIcon(icon)
            if registered_class:
                user.UnregisterClassW(class_name, instance)
            self.ready.set()
