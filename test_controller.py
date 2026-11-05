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


class OverrideTests(unittest.TestCase):
    def setUp(self):
        self.backend = Fake()
        self.logs = []
        self.controller = Controller(self.backend, self.logs.append)
        self.target = (10, r"C:\Apps\game.exe", 5)
        self.statuses = [-1073740008, 0]  # Already registered, then accepted.
        def register(handle, value):
            self.backend.events.append(("register", handle["path"], value))
            return self.statuses.pop(0)
        self.backend.register = register

    def actions(self):
        return [event[0] for event in self.backend.events if event[0] in ("register", "unregister")]

    def test_override_is_opt_in(self):
        self.controller.step(self.target)
        self.assertEqual(self.actions(), ["register"])
        self.assertIsNone(self.controller.active)

    def test_override_replaces_then_owns_new_registration(self):
        self.controller.step(self.target, allow_override=True)
        self.assertEqual(self.actions(), ["register", "unregister", "register"])
        self.assertEqual(self.controller.active.pid, 10)
        self.assertTrue(any("original request cannot be restored" in line for line in self.logs))
        self.controller.step(None, allow_override=True)
        self.assertIsNone(self.controller.active)
        self.assertEqual(self.actions()[-1], "unregister")

    def test_enabling_override_retries_previously_blocked_target(self):
        self.controller.step(self.target)
        self.statuses[:] = [-1073740008, 0]
        self.controller.step(self.target, allow_override=True)
        self.assertIsNotNone(self.controller.active)

    def test_denied_removal_does_not_register_or_retry_in_loop(self):
        self.backend.unreg_status = -1
        self.controller.step(self.target, allow_override=True)
        self.controller.step(self.target, allow_override=True)
        self.assertEqual(self.actions(), ["register", "unregister"])
        self.assertIsNone(self.controller.active)
        self.assertIn("Override denied", self.controller.block_reason)

    def test_failed_replacement_does_not_claim_or_remove_foreign_entry(self):
        self.statuses[:] = [-1073740008, -1073740008]
        self.controller.step(self.target, allow_override=True)
        self.controller.step(self.target, allow_override=True)
        self.controller.step(None, allow_override=True)
        self.assertEqual(self.actions(), ["register", "unregister", "register"])
        self.assertIsNone(self.controller.active)
        self.assertTrue(any("restart the app" in line for line in self.logs))

    def test_other_registration_errors_never_trigger_override(self):
        self.statuses[:] = [-1]
        self.controller.step(self.target, allow_override=True)
        self.assertEqual(self.actions(), ["register"])

    def test_process_exit_after_removal_prevents_replacement(self):
        original = self.backend.unregister
        def unregister(handle):
            result = original(handle)
            handle["alive"] = False
            return result
        self.backend.unregister = unregister
        self.controller.step(self.target, allow_override=True)
        self.assertEqual(self.actions(), ["register", "unregister"])
        self.assertIsNone(self.controller.active)

    def test_disappeared_registration_allows_one_replacement_attempt(self):
        self.backend.unreg_status = -1073741275  # STATUS_NOT_FOUND
        self.controller.step(self.target, allow_override=True)
        self.assertIsNotNone(self.controller.active)


if __name__ == "__main__":
    unittest.main()
