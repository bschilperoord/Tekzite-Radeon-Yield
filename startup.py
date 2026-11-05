"""Current-user sign-in entry; no scheduled task or elevation needed."""
from pathlib import Path
import subprocess

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "TekziteRadeonYield"


def startup_command(executable, script):
    executable = Path(executable)
    windowed = executable.with_name("pythonw.exe")
    if windowed.exists():
        executable = windowed
    command = subprocess.list2cmdline([str(executable), str(Path(script).resolve()), "--startup"])
    if len(command) > 260:
        raise OSError("Startup path is too long. Move the app to a shorter folder path.")
    return command


def is_enabled():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, VALUE_NAME)
            return bool(value)
    except FileNotFoundError:
        return False


def set_enabled(enabled, executable, script):
    import winreg
    if enabled:
        command = startup_command(executable, script)
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, VALUE_NAME)
        except FileNotFoundError:
            pass
