"""Version-pinned resource-manager request definitions."""
import ctypes as C
import hashlib

KNOWN_HASHES = {
    "rmclient.dll": "8d35323c8ad2215237e21d57e2b6cd4c0f98afc4e4ec4def221a11454fc9682a",
    "PsmServiceExtHost.dll": "8ab650e070aa6d95f041df1bb0c36caae8d7cf94f110b6b28341f77ea4f8e7da",
    "drivers/dxgkrnl.sys": "082058f0aa191d8ed1e2d6572f4680691689774a0b8421ba136da16c3d491642",
}


class ResourceRequest(C.Structure):
    _fields_ = [
        ("version", C.c_uint32),
        ("cpu_count", C.c_uint32),
        ("cpu_mask", C.c_uint64),
        ("gpu_yield", C.c_uint32),
        ("game_memory_budget", C.c_uint32),
        ("dwm_memory_budget", C.c_uint32),
        ("flags_1_raw", C.c_uint32),
        ("flags_2_raw", C.c_uint32),
        ("priority_class_raw", C.c_uint8),
        ("reserved", C.c_uint8 * 3),
    ]


def fields(request):
    return {name: (hex(getattr(request, name)) if name == "cpu_mask" else getattr(request, name))
            for name, _ in ResourceRequest._fields_ if name != "reserved"}


def validate_files(system32):
    hashes = {}
    for relative, expected in KNOWN_HASHES.items():
        actual = hashlib.sha256((system32 / relative).read_bytes()).hexdigest()
        hashes[relative] = actual
        if actual != expected:
            raise RuntimeError(f"{relative} differs from the analyzed version; no native query performed.")
    return hashes


