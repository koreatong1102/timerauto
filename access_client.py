"""Online approval protocol. No account tokens in config, logs or diagnostics."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler


class AccessError(Exception):
    pass


def validate_access_configuration():
    from access_policy import ONLINE_ACCESS_ENABLED, AUTH_SERVER_URL
    if ONLINE_ACCESS_ENABLED:
        validate_server(AUTH_SERVER_URL)


def validate_server(url):
    parsed = urlsplit(str(url))
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ("", "/") or parsed.port not in (None,443)):
        raise AccessError("인증 서버가 설정되지 않았습니다. 운영자에게 인증 서버 연결이 완료된 업데이트를 요청하세요.")
    return url.rstrip("/")


def device_id():
    # Hash only; never send the registry MachineGuid itself or a user/game ID.
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            guid = winreg.QueryValueEx(key,"MachineGuid")[0]
        if not isinstance(guid,str) or not guid.strip():
            raise ValueError("empty MachineGuid")
        return hashlib.sha256(("TimerAuto/access/v1:"+guid.strip().lower()).encode()).hexdigest()
    except (OSError,ValueError) as exc:
        raise AccessError("이 PC의 등록 정보를 읽지 못했습니다. 운영자에게 문의하세요.") from exc


def protect(data, decrypt=False):
    """Windows DPAPI: copied install folders cannot carry an approval token."""
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [("size",wintypes.DWORD),("data",ctypes.POINTER(ctypes.c_ubyte))]
    buf = ctypes.create_string_buffer(data)
    source = Blob(len(data),ctypes.cast(buf,ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    crypt = ctypes.WinDLL("crypt32",use_last_error=True)
    kernel = ctypes.WinDLL("kernel32",use_last_error=True)
    method = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    method.argtypes = [ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    method.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not method(ctypes.byref(source),None,None,None,None,1,ctypes.byref(output)):
        raise AccessError("PC 인증정보 보호/복호화에 실패했습니다. 운영자에게 PC 등록 초기화를 요청하세요.")
    try:
        return ctypes.string_at(output.data,output.size)
    finally:
        kernel.LocalFree(output.data)


def credential_path(server):
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        raise AccessError("Windows 사용자 저장 경로를 찾지 못했습니다.")
    return Path(base)/"TimerAuto"/"access"/(hashlib.sha256(server.encode()).hexdigest()[:24]+".bin")


def credentials(server):
    path = credential_path(server)
    identity = device_id()
    try:
        data = json.loads(protect(path.read_bytes(),decrypt=True))
        if not isinstance(data,dict) or data.get("device_id") != identity or not isinstance(data.get("token"),str) or not re.fullmatch(r"[0-9a-f]{64}",data["token"]):
            raise AccessError("PC 등록정보가 일치하지 않습니다. 운영자에게 초기화를 요청하세요.")
        return data
    except FileNotFoundError:
        data = {"device_id":identity,"token":secrets.token_hex(32)}
        path.parent.mkdir(parents=True,exist_ok=True)
        temp = path.with_suffix("."+secrets.token_hex(8)+".tmp")
        try:
            with temp.open("xb") as stream:
                stream.write(protect(json.dumps(data).encode()))
            # Do not replace another process's just-created credential.
            try:
                os.link(temp,path)
            except FileExistsError:
                return credentials(server)
        finally:
            temp.unlink(missing_ok=True)
        return data


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward a registration credential to another host.


class AccessClient:
    def __init__(self, server, identity=None):
        self.server = validate_server(server)
        self.identity = credentials(self.server) if identity is None else identity
        self.opener = build_opener(NoRedirect())

    def request(self, route, name=None):
        body = {"device_id":self.identity["device_id"]}
        if name is not None:
            body["name"] = name
        req = Request(self.server+route,data=json.dumps(body).encode(),method="POST",headers={
            "Content-Type":"application/json","Authorization":"Bearer "+self.identity["token"],
            "User-Agent":"TimerAuto-Access/1"})
        try:
            with self.opener.open(req,timeout=5) as response:
                raw = response.read(8193)
                if len(raw)>8192:
                    raise AccessError("인증 서버 응답이 올바르지 않습니다.")
                result = json.loads(raw)
            if not isinstance(result,dict) or result.get("status") not in ("approved","pending","revoked","unknown"):
                raise AccessError("인증 서버 응답이 올바르지 않습니다.")
            return result["status"]
        except HTTPError as exc:
            code = exc.code
            exc.close()
            if code in (401,403,409):
                return "revoked"
            raise AccessError("인증 서버에 연결하지 못했습니다. 잠시 후 다시 시도하세요.") from None
        except (OSError,ValueError) as exc:
            raise AccessError("인증 서버에 연결하지 못했습니다. 잠시 후 다시 시도하세요.") from None


class Lease:
    """Monotonic deadline: errors never extend authority; denial is immediate."""
    def __init__(self, grace=45, clock=time.monotonic):
        self.clock,self.grace = clock,grace
        self.deadline = 0

    def observe(self, status):
        if status == "approved":
            self.deadline = self.clock()+self.grace
            return True
        if status is not None:
            self.deadline = 0
            return False
        return self.clock()<self.deadline


def start_monitor(client, callback, *, interval=15, grace=45):
    cancel = threading.Event()
    def run():
        lease = Lease(grace)
        lease.observe("approved")  # Caller must first complete an online check.
        while not cancel.wait(min(interval,max(0,lease.deadline-time.monotonic()))):
            try:
                status = client.request("/api/check")
            except Exception:
                status = None
            if cancel.is_set():
                return
            if not lease.observe(status):
                callback("사용 권한이 중지되었습니다." if status is not None else "인증 서버 연결이 끊겨 사용을 중지합니다.")
                return
    thread = threading.Thread(target=run,daemon=True,name="OnlineAccessMonitor")
    thread.start()
    return cancel
