"""Tekzite Radeon Yield 1.4 — usable experimental Windows controller."""
import json
import ntpath
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

from controller import Controller, key, foreground_request

VERSION = "1.4 experimental"
CONFIG = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "TekziteRadeonYield" / "settings.json"


def worker():
    from windows_backend import Backend
    lock = threading.Lock()
    state = {"enabled": False, "value": 5, "apps": [], "automatic": True, "override": False, "closing": False,
             "retry": False, "list": False}
    wake = threading.Event()

    def send(value):
        try:
            print(json.dumps(value), flush=True)
        except (BrokenPipeError, OSError):
            pass  # UI may have exited; cleanup must still run.

    def receive():
        try:
            for line in sys.stdin:
                try:
                    command = json.loads(line)
                    with lock:
                        kind = command.get("type")
                        if kind == "settings":
                            state["enabled"] = bool(command.get("enabled"))
                            state["automatic"] = bool(command.get("automatic", True))
                            state["override"] = command.get("override") is True
                            value = command.get("value", 5)
                            state["value"] = value if type(value) is int and 2 <= value <= 10 else 5
                            state["apps"] = [path for path in command.get("apps", []) if isinstance(path, str)]
                        elif kind == "close":
                            state["closing"], state["enabled"] = True, False
                        elif kind == "retry":
                            state["retry"] = True
                        elif kind == "list":
                            state["list"] = True
                    wake.set()
                except (ValueError, TypeError):
                    pass
        finally:
            with lock:
                state["closing"], state["enabled"] = True, False
            wake.set()

    threading.Thread(target=receive, daemon=True).start()
    backend = None
    controller = None
    ui_pid = os.getppid()
    last_log = {}
    last_status = None

    def log(message):
        now = time.monotonic()
        if now - last_log.get(message, -100) < 10:
            return
        if len(last_log) > 300:
            last_log.clear()
        last_log[message] = now
        send({"type": "log", "message": message})

    try:
        backend = Backend()
        controller = Controller(backend, log)
        send({"type": "ready"})
        windows_root = key(str(backend.system32.parent)) + "\\"
        while True:
            with lock:
                current = state.copy()
                state["retry"], state["list"] = False, False
            if current["retry"]:
                controller.retry()
            if current["list"] and not current["closing"]:
                choices = [(pid, path) for pid, path in backend.processes()
                           if pid != ui_pid and not key(path).startswith(windows_root)]
                send({"type": "processes", "items": choices})
            foreground = backend.foreground()
            desired = foreground_request(
                foreground, enabled=current["enabled"], closing=current["closing"],
                automatic=current["automatic"], apps=current["apps"],
                excluded_pids=(os.getpid(), ui_pid), windows_root=windows_root,
                value=current["value"])
            try:
                if current["closing"]:
                    clean = controller.release()
                    message = "Stopped" if clean else "Cleanup pending — close the target app if this persists"
                else:
                    message = controller.step(desired, allow_override=current["override"])
                    if current["automatic"] and desired is None and controller.active is None:
                        message = "Waiting for app"
                    clean = controller.active is None
                    if not current["enabled"] and clean:
                        message = "Stopped"
            except Exception as error:
                log(str(error))
                with lock:
                    state["enabled"] = False
                current["enabled"] = False
                clean = controller.release()
                message = "Paused after an error; cleanup pending" if not clean else "Paused after an error — see activity"
            payload = {"type": "status", "message": message, "active": controller.active is not None,
                       "enabled": current["enabled"],
                       "foreground": foreground[1] if foreground else None,
                       "registered": controller.active.path if controller.active else None,
                       "yield": controller.active.value if controller.active else None,
                       "closing": current["closing"]}
            signature = json.dumps(payload)
            if signature != last_status:
                send(payload)
                last_status = signature
            if current["closing"] and clean:
                send({"type": "closed"})
                break
            wake.wait(0.5)
            wake.clear()
    except Exception as error:
        send({"type": "fatal", "message": str(error)})
    finally:
        if controller and controller.active:
            # Do not silently abandon an owned registration after UI pipe loss.
            while not controller.release():
                time.sleep(1)
        if backend:
            backend.shutdown()


def run_app():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    import startup
    from tray import Tray
    if os.name != "nt":
        print("Tekzite Radeon Yield requires Windows 11 and 64-bit Python.")
        return 1
    root = tk.Tk()
    root.title("Tekzite Radeon Yield")
    root.geometry("900x850")
    root.minsize(820, 810)
    try:
        root.iconbitmap(str(Path(__file__).with_name("tray.ico")))
    except tk.TclError:
        pass
    root.configure(bg="#13171e")
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TFrame", background="#13171e")
    style.configure("Card.TFrame", background="#202630")
    style.configure("TLabel", background="#13171e", foreground="#e9edf4", font=("Segoe UI", 10))
    style.configure("Muted.TLabel", foreground="#adb7c8")
    style.configure("Card.TLabel", background="#202630", foreground="#e9edf4")
    style.configure("TCheckbutton", background="#13171e", foreground="#e9edf4", font=("Segoe UI", 10))
    style.map("TCheckbutton", background=[("active", "#202630")], foreground=[("active", "#ffffff")])
    style.configure("Title.TLabel", font=("Segoe UI", 25, "bold"))
    style.configure("Value.TLabel", font=("Segoe UI", 29, "bold"), foreground="#ff6969")
    style.configure("TButton", font=("Segoe UI", 10), padding=7, background="#303a49", foreground="#f5f7fa")
    style.map("TButton", background=[("active", "#455168"), ("disabled", "#242b36")],
              foreground=[("disabled", "#7d8899")])
    style.configure("Treeview", background="#202630", fieldbackground="#202630", foreground="#e9edf4",
                    rowheight=27, font=("Segoe UI", 10))
    style.configure("Treeview.Heading", background="#303a49", foreground="#e9edf4", font=("Segoe UI", 10))
    apps = []
    initial_value = 5
    initial_automatic = True
    try:
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        initial_automatic = config.get("automatic", True) is not False
        apps = list(dict.fromkeys(str(path) for path in config.get("apps", [])
                                 if isinstance(path, str) and ntpath.isabs(path) and path.lower().endswith(".exe")))
        stored = config.get("yield", 5)
        if type(stored) is int and 2 <= stored <= 10:
            initial_value = stored
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    enabled, ready, closing, worker_active = False, False, False, False
    startup_launch = "--startup" in sys.argv[1:]
    tray = None
    picker = None
    logs = []
    inbound = queue.Queue()
    worker_python = Path(sys.executable)
    if worker_python.name.lower() == "pythonw.exe":
        worker_python = worker_python.with_name("python.exe")
    child = subprocess.Popen([str(worker_python), "-u", str(Path(__file__).resolve()), "--worker"],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW)

    def reader():
        for line in child.stdout:
            try:
                inbound.put(json.loads(line))
            except ValueError:
                pass
        inbound.put({"type": "exited"})
    threading.Thread(target=reader, daemon=True).start()

    panel = ttk.Frame(root, padding=24)
    panel.pack(fill="both", expand=True)
    ttk.Label(panel, text="Radeon Yield", style="Title.TLabel").pack(anchor="w")
    ttk.Label(panel, text="TEKZITE  /  " + VERSION,
              style="Muted.TLabel").pack(anchor="w", pady=(2, 18))
    card = ttk.Frame(panel, padding=16, style="Card.TFrame")
    card.pack(fill="x")
    status = tk.StringVar(value="Checking Windows compatibility…")
    foreground = tk.StringVar(value="Foreground: —")
    registered = tk.StringVar(value="Registered app: none")
    ttk.Label(card, textvariable=status, style="Card.TLabel", wraplength=790,
              font=("Segoe UI", 12, "bold")).pack(anchor="w")
    ttk.Label(card, textvariable=foreground, style="Card.TLabel", wraplength=790).pack(anchor="w", pady=(7, 0))
    ttk.Label(card, textvariable=registered, style="Card.TLabel", wraplength=790).pack(anchor="w", pady=(4, 0))
    value = tk.IntVar(value=initial_value)
    automatic = tk.BooleanVar(value=initial_automatic)
    override = tk.BooleanVar(value=False)  # Session only, including startup launches.
    value_text = tk.StringVar(value=f"{initial_value}%")
    ttk.Label(panel, text="GPU yield", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(18, 0))
    ttk.Label(panel, textvariable=value_text, style="Value.TLabel").pack(anchor="w")
    slider = tk.Scale(panel, from_=2, to=10, resolution=1, orient="horizontal", variable=value,
                      showvalue=False, bg="#13171e", fg="#e9edf4", troughcolor="#303a49",
                      highlightthickness=0, activebackground="#ff6969", length=780)
    slider.pack(fill="x")
    controls = ttk.Frame(panel)
    controls.pack(fill="x", pady=(10, 0))

    def log(text):
        entry = time.strftime("%H:%M:%S  ") + text
        logs.append(entry)
        del logs[:-500]
        output.configure(state="normal")
        output.insert("end", entry + "\n")
        if int(output.index("end-1c").split(".")[0]) > 200:
            output.delete("1.0", "40.0")
        output.see("end")
        output.configure(state="disabled")

    def send(command):
        try:
            child.stdin.write(json.dumps(command) + "\n")
            child.stdin.flush()
            return True
        except (OSError, BrokenPipeError):
            return False

    def save():
        try:
            CONFIG.parent.mkdir(parents=True, exist_ok=True)
            temp = CONFIG.with_name(f"settings-{os.getpid()}.tmp")
            temp.write_text(json.dumps({"yield": value.get(), "apps": apps, "automatic": automatic.get()}, indent=2), encoding="utf-8")
            temp.replace(CONFIG)
        except OSError as error:
            log("Could not save settings: " + str(error))

    def push():
        send({"type": "settings", "enabled": enabled, "value": value.get(), "apps": apps,
              "automatic": automatic.get(), "override": override.get()})

    def sync_buttons():
        toggle.configure(text="Stop" if enabled else "Start tracking",
                         state="normal" if ready and (automatic.get() or apps or enabled) and not closing else "disabled")

    def toggle_tracking():
        nonlocal enabled
        enabled = not enabled
        save()
        push()
        sync_buttons()

    toggle = ttk.Button(controls, text="Start tracking", command=toggle_tracking, state="disabled")
    toggle.pack(side="left")
    ttk.Button(controls, text="Retry app", command=lambda: send({"type": "retry"})).pack(side="left", padx=8)
    presets = ttk.Frame(controls)
    presets.pack(side="right")

    def change_preset(number):
        value.set(number)
        value_text.set(f"{number}%")
        save()
        push()
    for number in (2, 5, 10):
        ttk.Button(presets, text=f"{number}%", command=lambda n=number: change_preset(n)).pack(side="left", padx=3)

    def slider_change(_):
        value_text.set(f"{value.get()}%")
    slider.configure(command=slider_change)
    slider.bind("<ButtonRelease-1>", lambda event: (save(), push()))
    slider.bind("<KeyRelease>", lambda event: (save(), push()))
    def mode_changed():
        save()
        push()
        sync_buttons()
        log("Automatic foreground mode enabled." if automatic.get() else "Selected-app mode enabled.")

    ttk.Checkbutton(panel, text="Automatic foreground app",
                    variable=automatic, command=mode_changed).pack(anchor="w", pady=(15, 4))

    def change_override():
        nonlocal enabled
        if not override.get():
            enabled = False
        log("Game Mode override enabled for this session. Restart affected games to re-establish their normal Game Mode registration."
            if override.get() else "Override off; tracking stopped. Restart affected games for normal Game Mode.")
        push()
        sync_buttons()

    ttk.Checkbutton(panel, text="Override Game Mode (restart game to restore)", variable=override,
                    command=change_override).pack(anchor="w", pady=(0, 4))
    try:
        initial_startup = startup.is_enabled()
    except OSError:
        initial_startup = False
    startup_option = tk.BooleanVar(value=initial_startup)

    def change_startup():
        try:
            startup.set_enabled(startup_option.get(), sys.executable, __file__)
            log("Run at sign-in enabled." if startup_option.get() else "Run at sign-in disabled.")
        except OSError as error:
            startup_option.set(not startup_option.get())
            log("Startup: " + str(error))

    ttk.Checkbutton(panel, text="Run at sign-in", variable=startup_option,
                    command=change_startup).pack(anchor="w", pady=(0, 4))
    ttk.Label(panel, text="Selected apps", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(12, 5))
    table = ttk.Treeview(panel, columns=("app", "path"), show="headings", height=4)
    table.heading("app", text="App")
    table.heading("path", text="Executable")
    table.column("app", width=170, stretch=False)
    table.column("path", width=600)
    table.pack(fill="x")

    def render_apps():
        table.delete(*table.get_children())
        for path in apps:
            table.insert("", "end", values=(ntpath.basename(path), path))
        sync_buttons()

    def add_path(path):
        if not any(key(item) == key(path) for item in apps):
            apps.append(path)
            save()
            render_apps()
            push()

    def browse():
        path = filedialog.askopenfilename(title="Select an application executable", filetypes=[("Windows applications", "*.exe")])
        if path:
            add_path(ntpath.normpath(path))

    def remove():
        selected = {key(table.item(row, "values")[1]) for row in table.selection()}
        apps[:] = [path for path in apps if key(path) not in selected]
        save()
        render_apps()
        push()

    def pick_running():
        nonlocal picker
        if picker is not None and picker.winfo_exists():
            picker.lift()
            return
        picker = tk.Toplevel(root)
        picker.title("Choose a running app")
        picker.geometry("800x430")
        picker.configure(bg="#13171e")
        picker.transient(root)
        container = ttk.Frame(picker, padding=14)
        container.pack(fill="both", expand=True)
        picker.rows = ttk.Treeview(container, columns=("name", "pid", "path"), show="headings")
        for name, width in (("name", 170), ("pid", 70), ("path", 500)):
            picker.rows.heading(name, text=name.capitalize())
            picker.rows.column(name, width=width)
        picker.rows.pack(fill="both", expand=True)
        def choose():
            rows = picker.rows.selection()
            if rows:
                add_path(picker.rows.item(rows[0], "values")[2])
                picker.destroy()
        ttk.Button(container, text="Add selected app", command=choose).pack(anchor="e", pady=(8, 0))
        picker.rows.bind("<Double-1>", lambda event: choose())
        send({"type": "list"})

    apps_bar = ttk.Frame(panel)
    apps_bar.pack(fill="x", pady=7)
    ttk.Button(apps_bar, text="Add running app…", command=pick_running).pack(side="left")
    ttk.Button(apps_bar, text="Browse executable…", command=browse).pack(side="left", padx=8)
    ttk.Button(apps_bar, text="Remove selected", command=remove).pack(side="left")
    ttk.Label(panel, text="Activity", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(12, 4))
    output = tk.Text(panel, height=5, bg="#0e1218", fg="#c4cedf", insertbackground="#e9edf4",
                     state="disabled", wrap="word", relief="flat", font=("Consolas", 9))
    output.pack(fill="both", expand=True)

    def close():
        nonlocal closing, enabled
        if closing:
            return
        if child.poll() is not None:
            root.destroy()
            return
        closing, enabled = True, False
        save()
        send({"type": "close"})
        status.set("Restoring…")
        sync_buttons()
    def show():
        root.deiconify()
        root.lift()

    def hide():
        if child.poll() is not None:
            close()
        elif not closing and tray and tray.available:
            root.withdraw()
        else:
            close()

    root.protocol("WM_DELETE_WINDOW", hide)
    ttk.Button(apps_bar, text="Exit", command=close).pack(side="right")
    tray = Tray(lambda action: inbound.put({"type": "tray", "action": action}))
    if tray.available and startup_launch:
        root.withdraw()
    elif not tray.available:
        log("Tray unavailable — closing the window exits the app.")
    render_apps()

    def poll():
        nonlocal ready, enabled, worker_active, startup_launch
        destroy = False
        while True:
            try:
                message = inbound.get_nowait()
            except queue.Empty:
                break
            kind = message.get("type")
            if kind == "ready":
                ready = True
                status.set("Ready")
                log("Windows compatibility verified.")
                if startup_launch:
                    enabled = bool(automatic.get() or apps)
                    startup_launch = False
                push()
                sync_buttons()
            elif kind == "tray":
                action = message.get("action")
                if action == "show":
                    show()
                elif action == "toggle" and ready and not closing and (automatic.get() or apps or enabled):
                    toggle_tracking()
                elif action == "exit":
                    close()
                elif action == "tray_error":
                    show()
                    log("Tray unavailable.")
            elif kind == "log":
                log(message["message"])
            elif kind == "status":
                worker_active = bool(message.get("active"))
                enabled = bool(message.get("enabled"))
                sync_buttons()
                status.set(message["message"])
                foreground.set("Foreground: " + (ntpath.basename(message.get("foreground") or "") or "—"))
                registered.set("Registered app: " + (ntpath.basename(message.get("registered") or "") or "none"))
            elif kind == "processes" and picker is not None and picker.winfo_exists():
                picker.rows.delete(*picker.rows.get_children())
                for pid, path in sorted(message["items"], key=lambda row: ntpath.basename(row[1]).lower()):
                    picker.rows.insert("", "end", values=(ntpath.basename(path), pid, path))
            elif kind == "fatal":
                ready, enabled = False, False
                show()
                status.set("Unavailable — " + message["message"])
                log(message["message"])
                sync_buttons()
            elif kind == "closed":
                destroy = closing
            elif kind == "exited":
                ready, enabled = False, False
                sync_buttons()
                if closing:
                    destroy = True
                elif status.get().startswith("Unavailable") is False:
                    show()
                    status.set("Controller exited — close and reopen the app")
        if destroy:
            root.destroy()
        else:
            root.after(150, poll)
    root.after(150, poll)
    try:
        root.mainloop()
    finally:
        if tray:
            tray.close()
        # EOF tells the independent worker to restore even if the UI is killed.
        try:
            child.stdin.close()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            stream.reconfigure(encoding="utf-8")
    if sys.argv[1:] == ["--worker"]:
        worker()
    else:
        raise SystemExit(run_app())
