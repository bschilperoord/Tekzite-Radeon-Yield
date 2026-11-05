# Tekzite Radeon Yield

Experimental Windows desktop app for foreground GPU yield requests through the
Windows Game Mode resource-manager broker. Written in Python with Tkinter and
native Windows APIs; no third-party Python packages are required.

## Features

- GPU yield request slider: 2–10%.
- Automatic foreground tracking or a selected-app list.
- Tray icon with Show, Start / stop tracking, and Exit.
- Optional Run at sign-in, with tracking started in the tray.
- Saved preferences, activity messages, and registration cleanup on Stop / Exit.

## Status and compatibility

**Version 1.3 is experimental.** A successful request is not proof of an exact
GPU time allocation or a performance improvement. This is not equivalent to an
arbitrary NVIDIA-style percentage allocation slider.

The broker route was exercised on one Windows 11 installation with a Radeon RX
7900 XTX. The complete GUI, tray, and startup integration have not been exercised
in the build environment. Sixteen automated controller and startup checks pass
offline.

This release uses an undocumented Windows interface and is deliberately pinned
to specific hashes of `rmclient.dll`, `PsmServiceExtHost.dll`, and `dxgkrnl.sys`.
The checked kernel component is version 10.0.26100.9818. The hashes are in
`broker_contract.py`. Most other installations, including updated versions, may
show **Unavailable**. Do not remove these checks to force compatibility: the
private request layout must be checked for each supported Windows build.

The backend is Windows-specific, not a proprietary AMD driver API. Other GPU
vendors and actual GPU scheduling effects have not been verified.

## Run

1. Install 64-bit Python 3 with Tkinter on Windows 11.
2. Extract the app to a permanent folder. Exit any previous copy.
3. Double-click **Start.cmd**, or run `python app.py` from the app folder.
4. Choose a yield value and click **Start tracking**. Automatic foreground mode
   is enabled by default. Turn it off to use the selected-app list.

Closing the window keeps the app in the tray. Click its red T icon to show it,
or right-click for controls. **Stop & restore** removes the app's registration;
**Exit** removes it and quits. If no tray icon can be created, closing the window
exits instead. Windows may put the icon in the hidden-icons menu.

**Run at sign-in** creates an entry only for the current user. Sign-in launches
start tracking using saved settings. Manual launches start stopped. Disable the
option before deleting the app; after moving it, toggle the option off and on
from the new folder. No administrator rights are needed to configure startup.

Settings are stored at `%LOCALAPPDATA%\TekziteRadeonYield\settings.json`.

## How requests work

The app initializes a version 6 resource request and registers the focused
process through `RmGameModeRegisterProcess`. It requests a yield target of 2–10
and GPU memory budget targets of 50% for the game and 30% for the compositor.
Those budget targets are coupled to this broker path; they are not fixed VRAM
partitions. GPU policy can affect scheduling beyond one process.

No exclusive CPU count, CPU mask, or CPU priority class is requested. The app
does not change CPU affinity, power plans, drivers, or firmware. It does not
inject into games or impersonate a Windows service. System DLLs are loaded from
Windows and are not redistributed here.

Windows system apps and the controller's own processes are excluded. Only the
process owning the foreground window is targeted; child processes doing GPU
work are not automatically included. Elevated or protected apps can reject
access. Games already registered by Windows Game Mode or another controller are
left alone. Rejections appear in Activity; **Retry app** retries the focused app.

## Cleanup

A separate worker owns accepted registrations and process handles. It removes
the old registration before activating another app. Closing or crashing the UI
signals the worker through pipe closure; it attempts cleanup and retries if
removal fails. Closing the target process lets Windows handle process-exit
cleanup. Held handles prevent accidental use of a recycled process ID.

Windows owns policy restoration. Successful unregistration is not independent
readback of GPU policy. Forcibly terminating both UI and worker can interrupt
cleanup. Avoid running another yield controller against the same process.

## Development

```console
python -m unittest discover -v
python -m compileall -q .
```

- `app.py`: GUI and worker communication.
- `controller.py`: foreground selection, ownership and cleanup.
- `windows_backend.py`, `broker_contract.py`: native bindings and compatibility.
- `tray.py`, `tray.ico`: notification icon.
- `startup.py`: current-user sign-in entry.

Do not post private diagnostics or proprietary Windows binaries in issues.
Reports should include app version, Windows build, GPU model and driver version,
and the relevant Activity message.

This project is independent of AMD, NVIDIA, and Microsoft.

Windows integration references:
[notification icons](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/ns-shellapi-notifyicondataw),
[Run entries](https://learn.microsoft.com/en-us/windows/win32/setupapi/run-and-runonce-registry-keys).
