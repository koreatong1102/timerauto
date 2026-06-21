from __future__ import annotations

import ctypes
from ctypes import wintypes
import threading
from typing import Callable, Dict, List, Optional, Tuple

# ============================================================
# WinAPI (key send / hotkeys)
# ============================================================
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

ULONG_PTR = ctypes.c_uint64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_uint32
LONG_PTR = ctypes.c_int64 if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_int32

LRESULT = getattr(wintypes, "LRESULT", LONG_PTR)
HHOOK = getattr(wintypes, "HHOOK", wintypes.HANDLE)
HINSTANCE = getattr(wintypes, "HINSTANCE", wintypes.HANDLE)

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
MAPVK_VK_TO_VSC = 0


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", INPUT_UNION)]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


LowLevelProc = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

_user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
_user32.SendInput.restype = wintypes.UINT
_user32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
_user32.MapVirtualKeyW.restype = wintypes.UINT
_user32.keybd_event.argtypes = (wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ULONG_PTR)
_user32.keybd_event.restype = None

_user32.SetWindowsHookExW.argtypes = (ctypes.c_int, LowLevelProc, HINSTANCE, wintypes.DWORD)
_user32.SetWindowsHookExW.restype = HHOOK
_user32.CallNextHookEx.argtypes = (HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
_user32.CallNextHookEx.restype = LRESULT
_user32.UnhookWindowsHookEx.argtypes = (HHOOK,)
_user32.UnhookWindowsHookEx.restype = wintypes.BOOL
_user32.GetMessageW.argtypes = (ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
_user32.GetMessageW.restype = ctypes.c_int
_user32.PostThreadMessageW.argtypes = (wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
_user32.PostThreadMessageW.restype = wintypes.BOOL
_kernel32.GetCurrentThreadId.argtypes = ()
_kernel32.GetCurrentThreadId.restype = wintypes.DWORD
_kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
_kernel32.GetModuleHandleW.restype = HINSTANCE


EXTENDED_VK = {
    0x21, 0x22, 0x23, 0x24,
    0x25, 0x26, 0x27, 0x28,
    0x2D, 0x2E,
    0xA3, 0xA5,
}


def press_vk_once(vk: int) -> Tuple[bool, int]:
    try:
        vk = int(vk) & 0xFF
    except Exception:
        return False, 87

    scan = _user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC) & 0xFFFF
    ext = KEYEVENTF_EXTENDEDKEY if vk in EXTENDED_VK else 0

    down = INPUT()
    down.type = INPUT_KEYBOARD
    down.u.ki = KEYBDINPUT(0, scan, KEYEVENTF_SCANCODE | ext, 0, ULONG_PTR(0))

    up = INPUT()
    up.type = INPUT_KEYBOARD
    up.u.ki = KEYBDINPUT(0, scan, KEYEVENTF_SCANCODE | ext | KEYEVENTF_KEYUP, 0, ULONG_PTR(0))

    arr = (INPUT * 2)(down, up)
    sent = _user32.SendInput(2, arr, ctypes.sizeof(INPUT))
    if sent == 2:
        return True, 0

    err = int(ctypes.get_last_error())
    try:
        _user32.keybd_event(vk, 0, 0, ULONG_PTR(0))
        _user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, ULONG_PTR(0))
        return True, 0
    except Exception:
        return False, err


def build_vk_map() -> Dict[str, Optional[int]]:
    m: Dict[str, Optional[int]] = {}
    m["없음"] = None

    m["Esc"] = 0x1B
    m["ScrollLock"] = 0x91
    m["PauseBreak"] = 0x13
    m["CapsLock"] = 0x14
    m["NumLock"] = 0x90
    m["PrintScreen"] = 0x2C
    m["Insert"] = 0x2D
    m["Delete"] = 0x2E
    m["Home"] = 0x24
    m["End"] = 0x23
    m["PageUp"] = 0x21
    m["PageDown"] = 0x22
    m["Tab"] = 0x09
    m["Space"] = 0x20
    m["Enter"] = 0x0D

    m["Left"] = 0x25
    m["Up"] = 0x26
    m["Right"] = 0x27
    m["Down"] = 0x28

    for i in range(1, 13):
        m[f"F{i}"] = 0x70 + (i - 1)
    for i in range(10):
        m[str(i)] = 0x30 + i
    for i in range(26):
        m[chr(ord("A") + i)] = 0x41 + i
    return m


class GlobalHotkeys:
    def __init__(self):
        self._hook = None
        self._proc = None
        self._thread = None
        self._thread_id = 0
        self._stop = threading.Event()
        self._down = set()
        self._lock = threading.Lock()
        self._bindings: Dict[int, Callable[[], None]] = {}

    def set_bindings(self, bindings: Dict[int, Callable[[], None]]):
        with self._lock:
            self._bindings = dict(bindings)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread_id:
            _user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)

    def _run(self):
        self._thread_id = int(_kernel32.GetCurrentThreadId())

        @LowLevelProc
        def _callback(nCode, wParam, lParam):
            if nCode == 0:
                kbd = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                vk = int(kbd.vkCode)
                if wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    if vk not in self._down:
                        self._down.add(vk)
                        with self._lock:
                            cb = self._bindings.get(vk)
                        if cb is not None:
                            try:
                                cb()
                            except Exception:
                                pass
                elif wParam in (WM_KEYUP, WM_SYSKEYUP):
                    self._down.discard(vk)
            return _user32.CallNextHookEx(self._hook, nCode, wParam, lParam)

        self._proc = _callback
        hmod = _kernel32.GetModuleHandleW(None)
        self._hook = _user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, hmod, 0)
        if not self._hook:
            return

        msg = MSG()
        while not self._stop.is_set():
            r = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r == 0 or r == -1:
                break

        try:
            if self._hook:
                _user32.UnhookWindowsHookEx(self._hook)
        except Exception:
            pass
        self._hook = None


# ============================================================
# Audio features
# ============================================================
def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x * x) + 1e-12))


def linear_resample(x: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    x = x.astype(np.float32, copy=False)
    if src_sr == dst_sr:
        return x
    if len(x) < 2:
        return np.zeros(1, dtype=np.float32)
    dur = len(x) / float(src_sr)
    n_new = max(1, int(dur * dst_sr))
    t_old = np.linspace(0.0, dur, num=len(x), endpoint=False)
    t_new = np.linspace(0.0, dur, num=n_new, endpoint=False)
    return np.interp(t_new, t_old, x).astype(np.float32)


def agc_softclip(x: np.ndarray, target_rms: float = 0.06, max_gain: float = 25.0) -> np.ndarray:
    x = x.astype(np.float32, copy=False)
    r = rms(x)
    if r <= 1e-8:
        return x
    g = target_rms / r
    g = float(np.clip(g, 1.0 / max_gain, max_gain))
    return np.tanh(x * g).astype(np.float32)


class Biquad:
    def __init__(self, b0, b1, b2, a0, a1, a2):
        self.b0 = b0 / a0
        self.b1 = b1 / a0
        self.b2 = b2 / a0
        self.a1 = a1 / a0
        self.a2 = a2 / a0
        self.z1 = 0.0
        self.z2 = 0.0

    def process(self, x: np.ndarray) -> np.ndarray:
        y = np.empty_like(x, dtype=np.float32)
        b0, b1, b2, a1, a2 = self.b0, self.b1, self.b2, self.a1, self.a2
        z1, z2 = self.z1, self.z2
        for i in range(len(x)):
            xi = float(x[i])
            yi = b0 * xi + z1
            z1 = b1 * xi - a1 * yi + z2
            z2 = b2 * xi - a2 * yi
            y[i] = yi
        self.z1, self.z2 = z1, z2
        return y


def biquad_lowpass(fs: float, f0: float, q: float = 0.707) -> Biquad:
    w0 = 2.0 * np.pi * (f0 / fs)
    cw = np.cos(w0)
    sw = np.sin(w0)
    alpha = sw / (2.0 * q)
    b0 = (1 - cw) / 2
    b1 = 1 - cw
    b2 = (1 - cw) / 2
    a0 = 1 + alpha
    a1 = -2 * cw
    a2 = 1 - alpha
    return Biquad(b0, b1, b2, a0, a1, a2)


def biquad_highpass(fs: float, f0: float, q: float = 0.707) -> Biquad:
    w0 = 2.0 * np.pi * (f0 / fs)
    cw = np.cos(w0)
    sw = np.sin(w0)
    alpha = sw / (2.0 * q)
    b0 = (1 + cw) / 2
    b1 = -(1 + cw)
    b2 = (1 + cw) / 2
    a0 = 1 + alpha
    a1 = -2 * cw
    a2 = 1 - alpha
    return Biquad(b0, b1, b2, a0, a1, a2)


class SpeechBandFilter:
    def __init__(self, fs=16000, hp=120.0, lp=4800.0):
        self.hpf = biquad_highpass(fs, hp)
        self.lpf = biquad_lowpass(fs, lp)

    def process(self, x: np.ndarray) -> np.ndarray:
        return self.lpf.process(self.hpf.process(x))


def hz_to_mel(hz: np.ndarray) -> np.ndarray:
    return 2595.0 * np.log10(1.0 + hz / 700.0)


def mel_to_hz(mel: np.ndarray) -> np.ndarray:
    return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)


def mel_filterbank(sr: int, nfft: int, n_mels: int = 40, fmin: float = 80.0, fmax: float = 7600.0) -> np.ndarray:
    fmax = min(fmax, sr / 2.0)
    mmin = hz_to_mel(np.array([fmin], dtype=np.float32))[0]
    mmax = hz_to_mel(np.array([fmax], dtype=np.float32))[0]
    m = np.linspace(mmin, mmax, n_mels + 2, dtype=np.float32)
    hz = mel_to_hz(m)
    bins = np.floor((nfft + 1) * hz / sr).astype(np.int32)
    bins = np.clip(bins, 0, nfft // 2)

    fb = np.zeros((n_mels, nfft // 2 + 1), dtype=np.float32)
    for i in range(n_mels):
        left, center, right = bins[i], bins[i + 1], bins[i + 2]
        if center <= left:
            center = left + 1
        if right <= center:
            right = center + 1
        left = min(left, nfft // 2)
        center = min(center, nfft // 2)
        right = min(right, nfft // 2)

        for k in range(left, center):
            fb[i, k] = (k - left) / float(center - left + 1e-9)
        for k in range(center, right):
            fb[i, k] = (right - k) / float(right - center + 1e-9)

    fb /= (fb.sum(axis=1, keepdims=True) + 1e-9)
    return fb


def stft_power(x: np.ndarray, nfft: int, hop: int, window: np.ndarray) -> np.ndarray:
    if len(x) < nfft:
        x = np.pad(x, (0, nfft - len(x)))
    frames = 1 + (len(x) - nfft) // hop
    if frames <= 0:
        frames = 1
    out = np.empty((frames, nfft // 2 + 1), dtype=np.float32)
    idx = 0
    for fi in range(frames):
        seg = x[idx:idx + nfft]
        if len(seg) < nfft:
            seg = np.pad(seg, (0, nfft - len(seg)))
        spec = np.fft.rfft(seg * window)
        out[fi] = (np.abs(spec) ** 2).astype(np.float32)
        idx += hop
    return out


def logmel_feat(x16: np.ndarray, sr: int, nfft: int, hop: int, fb: np.ndarray, window: np.ndarray) -> np.ndarray:
    x16 = x16.astype(np.float32, copy=False)
    x16 = x16 - float(np.mean(x16))
    P = stft_power(x16, nfft=nfft, hop=hop, window=window)
    M = P @ fb.T
    M = np.log1p(M).astype(np.float32)
    M = M - M.mean(axis=1, keepdims=True)
    M = M / (M.std(axis=1, keepdims=True) + 1e-6)
    return M


def pick_loudest_segment(x: np.ndarray, seg_len: int) -> np.ndarray:
    if len(x) <= seg_len:
        return np.pad(x, (0, seg_len - len(x))).astype(np.float32)
    step = max(1, seg_len // 6)
    best_r, best_i = -1.0, 0
    for i in range(0, len(x) - seg_len + 1, step):
        seg = x[i:i + seg_len]
        r = rms(seg)
        if r > best_r:
            best_r, best_i = r, i
    return x[best_i:best_i + seg_len].astype(np.float32)


class TemplateRef:
    def __init__(self, vec: np.ndarray, frames: int, name: str, thr: float, user_index: int):
        self.vec = vec.astype(np.float32, copy=False)
        self.frames = int(frames)
        self.name = str(name)
        self.thr = float(thr)
        self.user_index = int(user_index)
