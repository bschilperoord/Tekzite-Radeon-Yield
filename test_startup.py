import subprocess
import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import startup


class StartupTests(unittest.TestCase):
    def test_command_quotes_paths_and_uses_windowed_python(self):
        with TemporaryDirectory(prefix="Radeon Yield ") as folder:
            root = Path(folder)
            (root / "pythonw.exe").touch()
            script = root / "app with spaces.py"
            result = startup.startup_command(root / "python.exe", script)
            self.assertEqual(result, subprocess.list2cmdline([
                str(root / "pythonw.exe"), str(script.resolve()), "--startup"]))

    def test_rejects_run_entry_longer_than_windows_limit(self):
        with self.assertRaises(OSError):
            startup.startup_command("python.exe", "x" * 300 + ".py")

    def test_enabling_and_disabling_only_changes_our_run_value(self):
        entries = {"OtherApp": "untouched"}
        class Key:
            def __enter__(self):
                return self
            def __exit__(self, *_):
                pass
        def query(key, name):
            if name not in entries:
                raise FileNotFoundError()
            return entries[name], 1
        def delete(key, name):
            if name not in entries:
                raise FileNotFoundError()
            del entries[name]
        registry = types.SimpleNamespace(
            HKEY_CURRENT_USER="HKCU", KEY_SET_VALUE=2, REG_SZ=1,
            OpenKey=lambda *args: Key(), CreateKeyEx=lambda *args: Key(),
            QueryValueEx=query, DeleteValue=delete,
            SetValueEx=lambda key, name, unused, kind, value: entries.update({name: value}))
        with patch.dict(sys.modules, winreg=registry):
            self.assertFalse(startup.is_enabled())
            startup.set_enabled(True, "python.exe", "app.py")
            self.assertTrue(startup.is_enabled())
            self.assertIn("--startup", entries[startup.VALUE_NAME])
            startup.set_enabled(False, "python.exe", "app.py")
            startup.set_enabled(False, "python.exe", "app.py")
            self.assertEqual(entries, {"OtherApp": "untouched"})


if __name__ == "__main__":
    unittest.main()
