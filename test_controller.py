import unittest
from controller import Controller, key, foreground_request


class ForegroundModeTests(unittest.TestCase):
    def choose(self, foreground=(10, r"C:\Apps\game.exe"), **overrides):
        options = dict(enabled=True, closing=False, automatic=True, apps=[],
                       excluded_pids=(90, 91), windows_root=r"C:\Windows", value=5)
        options.update(overrides)
        return foreground_request(foreground, **options)

    def test_automatic_mode_needs_no_app_list(self):
        self.assertEqual(self.choose(), (10, r"C:\Apps\game.exe", 5))

    def test_manual_mode_requires_selected_executable(self):
        self.assertIsNone(self.choose(automatic=False))
        self.assertIsNotNone(self.choose(automatic=False, apps=["c:/apps/GAME.EXE"]))

    def test_system_and_controller_exclusions_still_apply(self):
        for foreground in [(90, r"C:\Apps\app.exe"), (91, r"C:\Apps\app.exe"),
                           (10, "c:/WINDOWS/System32/taskmgr.exe"),
                           (10, r"C:\Windows\explorer.exe")]:
            with self.subTest(foreground=foreground):
                self.assertIsNone(self.choose(foreground))
        self.assertIsNotNone(self.choose((10, r"C:\WindowsGames\game.exe")))

    def test_stopped_closing_and_no_focus_never_activate(self):
        self.assertIsNone(self.choose(enabled=False))
        self.assertIsNone(self.choose(closing=True))
        self.assertIsNone(self.choose(None))

    def test_automatic_focus_switch_restores_previous_registration(self):
        backend = Fake()
        controller = Controller(backend, lambda _: None)
        controller.step(self.choose())
        controller.step(self.choose((20, r"C:\Apps\other.exe")))
        actions = [event[0] for event in backend.events if event[0] in ("register", "unregister")]
        self.assertEqual(actions, ["register", "unregister", "register"])
        self.assertEqual(controller.active.pid, 20)
        controller.step(self.choose((90, r"C:\Apps\controller.exe")))
        self.assertIsNone(controller.active)


class Fake:
    def __init__(self):
        self.entries = {10: {"path": r"C:\Apps\game.exe", "alive": True},
                        20: {"path": r"C:\Apps\other.exe", "alive": True}}
        self.events = []
        self.reg_status = 0
        self.unreg_status = 0
    def open(self, pid):
        self.events.append(("open", pid))
        return self.entries[pid]
    def path(self, handle):
        return handle["path"]
    def alive(self, handle):
        return handle["alive"]
    def close(self, handle):
        self.events.append(("close", handle["path"]))
    def register(self, handle, value):
        self.events.append(("register", handle["path"], value))
        return self.reg_status
    def unregister(self, handle):
        self.events.append(("unregister", handle["path"]))
        return self.unreg_status


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.b = Fake()
        self.log = []
        self.c = Controller(self.b, self.log.append)
        self.desired = (10, r"C:\Apps\game.exe", 5)

    def test_focus_loss_removes_only_our_registration(self):
        self.c.step(self.desired)
        self.assertIsNotNone(self.c.active)
        self.c.step(None)
        self.assertIsNone(self.c.active)
        self.assertIn(("unregister", r"C:\Apps\game.exe"), self.b.events)

    def test_existing_registration_is_not_removed_or_retried_continuously(self):
        self.b.reg_status = -1073740008  # 0xC0000718
        self.c.step(self.desired)
        self.c.step(self.desired)
        self.c.step(None)
        self.assertIsNone(self.c.active)
        self.assertFalse(any(event[0] == "unregister" for event in self.b.events))
        self.assertEqual(sum(event[0] == "register" for event in self.b.events), 1)

    def test_pending_cleanup_blocks_next_activation(self):
        self.c.step(self.desired)
        self.b.unreg_status = -1
        self.c.step((20, r"C:\Apps\other.exe", 5))
        self.assertEqual(self.c.active.pid, 10)
        self.assertFalse(any(event[0] == "register" and event[1].endswith("other.exe") for event in self.b.events))
        self.b.unreg_status = 0
        self.c.step((20, r"C:\Apps\other.exe", 5))
        self.assertEqual(self.c.active.pid, 20)

    def test_slider_change_unregisters_before_new_value(self):
        self.c.step(self.desired)
        self.c.step((10, r"C:\Apps\game.exe", 2))
        actions = [event[0] for event in self.b.events if event[0] in ("register", "unregister")]
        self.assertEqual(actions, ["register", "unregister", "register"])
        self.assertEqual(self.c.active.value, 2)

    def test_exited_process_never_unregisters_recycled_pid(self):
        self.c.step(self.desired)
        old = self.b.entries[10]
        old["alive"] = False
        self.b.entries[10] = {"path": r"C:\Apps\game.exe", "alive": True}
        self.c.step(self.desired)
        self.assertIs(self.c.active.handle, self.b.entries[10])
        self.assertFalse(any(event[0] == "unregister" for event in self.b.events))

    def test_path_rechecked_before_native_registration(self):
        self.b.entries[10]["path"] = r"C:\Apps\replacement.exe"
        self.c.step(self.desired)
        self.assertIsNone(self.c.active)
        self.assertFalse(any(event[0] == "register" for event in self.b.events))

    def test_windows_path_normalization(self):
        self.assertEqual(key("C:/Apps/GAME.EXE"), key(r"c:\apps\game.exe"))

    def test_explicit_retry_clears_rejection(self):
        self.b.reg_status = -1
        self.c.step(self.desired)
        self.b.reg_status = 0
        self.c.step(self.desired)
        self.assertIsNone(self.c.active)
        self.c.retry()
        self.c.step(self.desired)
        self.assertIsNotNone(self.c.active)


if __name__ == "__main__":
    unittest.main()
