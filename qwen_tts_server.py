"""Optional isolated Qwen3 CustomVoice server. Never imported by TimerAuto.

Run with the separately installed Python 3.12 environment, not timerauto.exe.
Only numeric loopback is exposed. No file paths or remote audio are accepted.
"""
import argparse
import io
import json
import math
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODELS = {size: f"Qwen/Qwen3-TTS-12Hz-{size}-CustomVoice" for size in ("0.6B", "1.7B")}


class Engine:
    def __init__(self, model_id):
        self.model_id = model_id
        self.ready = False
        self.error = ""
        self.device = "not loaded"
        self.speakers = []
        self.lock = threading.Lock()
        self.metrics = {}
        self.generated_count = 0

    def load(self, device="auto", cpu_threads=2):
        import torch
        from qwen_tts import Qwen3TTSModel
        torch.set_num_threads(cpu_threads)
        self.device = ("cuda:0" if torch.cuda.is_available() else "cpu") if device == "auto" else device
        if self.device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("CUDA PyTorch/GPU is not available. Check the isolated environment.")
        self.model = Qwen3TTSModel.from_pretrained(self.model_id, device_map=self.device,
            dtype=torch.float16 if self.device.startswith("cuda") else torch.float32,
            attn_implementation="sdpa")
        self.speakers = list(self.model.get_supported_speakers())
        self.ready = True

    def synthesize(self, options):
        import numpy as np
        import soundfile as sf
        import torch
        started = time.monotonic()
        instruction = options["instruction"] if "1.7B" in self.model_id else ""
        with torch.inference_mode():
            wavs, sample_rate = self.model.generate_custom_voice(text=options["text"],
                language=options["language"], speaker=options["speaker"],
                instruct=instruction or None, max_new_tokens=2048)
        inference_done = time.monotonic()
        audio = np.asarray(wavs[0], dtype=np.float32).reshape(-1)
        if options["speed"] != 1.:
            import librosa
            audio = librosa.effects.time_stretch(audio, rate=options["speed"])
        if not len(audio) or not np.isfinite(audio).all() or len(audio) > sample_rate * 120:
            raise ValueError("Model returned invalid or overlong audio.")
        audio = np.clip(audio * options["gain"], -1., 1.)
        output = io.BytesIO()
        sf.write(output, audio, int(sample_rate), format="WAV", subtype="PCM_16")
        elapsed = time.monotonic() - started
        self.generated_count += 1
        self.metrics = {"generation_ms": round(elapsed * 1000),
                        "inference_ms": round((inference_done - started) * 1000),
                        "postprocess_ms": round((time.monotonic() - inference_done) * 1000),
                        "rtf": round(elapsed / (len(audio) / sample_rate), 3),
                        "request_index": self.generated_count,
                        "audio_seconds": round(len(audio) / sample_rate, 3), "characters": len(options["text"])}
        print("QWEN_GENERATED " + json.dumps(self.metrics), flush=True)
        return output.getvalue()


def validate_request(data, engine):
    if not isinstance(data, dict) or data.get("model") != engine.model_id:
        raise ValueError("설정 모델과 서버 모델이 다릅니다. 0.6B / 1.7B 선택을 맞춰 주세요.")
    text = data.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > 1200:
        raise ValueError("문장은 1~1200자로 입력해 주세요.")
    speaker = str(data.get("speaker", ""))
    if speaker.lower() not in {str(value).lower() for value in engine.speakers}:
        raise ValueError("지원되지 않는 목소리입니다. 서버의 speakers 목록을 확인해 주세요.")
    language = data.get("language", "Korean")
    if language not in ("Korean", "English", "Auto"):
        raise ValueError("지원 언어는 Korean, English, Auto입니다.")
    instruction = data.get("instruction", "")
    if not isinstance(instruction, str) or len(instruction) > 500:
        raise ValueError("말투 지시는 500자 이하로 입력해 주세요.")
    gain, speed = float(data.get("gain", 1)), float(data.get("speed", 1))
    if not math.isfinite(gain) or not math.isfinite(speed) or not 0 <= gain <= 1 or not .7 <= speed <= 1.5:
        raise ValueError("음량/배속 범위를 확인해 주세요.")
    return {"text": text.strip(), "speaker": speaker, "language": language,
            "instruction": instruction, "gain": gain, "speed": speed}


def make_server(engine, port):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, *_):
            pass  # Never log user commentary text or request headers.

        def reply(self, status, value, mime="application/json"):
            content = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode("utf-8")
            try:
                self.send_response(status)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(content)
            except (ConnectionError, TimeoutError):
                # Windows also raises ConnectionAbortedError / WinError 10053
                # when a client expires during synthesis. No traceback flood.
                print("QWEN_CLIENT_DISCONNECTED response_discarded=true", flush=True)

        def do_GET(self):
            if self.path != "/health":
                return self.reply(404, {"error": "not found"})
            self.reply(200, {"service": "rfc-qwen3", "ready": engine.ready, "model": engine.model_id,
                "device": engine.device, "speakers": engine.speakers,
                "busy": engine.lock.locked(), "metrics": engine.metrics, "error": engine.error})

        def do_POST(self):
            if self.path != "/synthesize":
                return self.reply(404, {"error": "not found"})
            if self.headers.get("X-RFC-TTS") != "1" or self.headers.get("Origin") or self.headers.get_content_type() != "application/json":
                return self.reply(403, {"error": "local JSON client required"})
            if not engine.ready:
                return self.reply(503, {"error": "모델을 준비 중이거나 로딩에 실패했습니다. 서버 창을 확인해 주세요."})
            if not engine.lock.acquire(blocking=False):
                return self.reply(503, {"error": "이전 음성을 생성 중입니다. 오래된 콜을 쌓지 않고 생략합니다."})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 32768:
                    return self.reply(413, {"error": "request too large or empty"})
                data = json.loads(self.rfile.read(size))
                options = validate_request(data, engine)
                try:
                    audio = engine.synthesize(options)
                except Exception as exc:
                    print(f"QWEN_SYNTHESIS_ERROR {type(exc).__name__}", flush=True)
                    return self.reply(500, {"error": "모델 음성 생성에 실패했습니다. GPU 메모리와 서버 창을 확인해 주세요."})
                self.reply(200, audio, "audio/wav")
            except (ValueError, TypeError, OverflowError, UnicodeError) as exc:
                self.reply(400, {"error": str(exc)[:220]})
            finally:
                engine.lock.release()

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 8
    return Server(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=MODELS, default="1.7B")
    parser.add_argument("--port", type=int, default=8768)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda:0"), default="auto")
    parser.add_argument("--cpu-threads", type=int, default=2)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535 or not 1 <= args.cpu_threads <= 16:
        parser.error("port must be 1024..65535; CPU threads must be 1..16")
    engine = Engine(MODELS[args.model])
    server = make_server(engine, args.port)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    print(f"Loading {engine.model_id}. First run downloads model weights; this may take several minutes.", flush=True)
    try:
        engine.load(args.device, args.cpu_threads)
        print(f"READY http://127.0.0.1:{args.port} device={engine.device}. Ctrl+C stops the server.", flush=True)
        while worker.is_alive():
            worker.join(1)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        engine.error = f"{type(exc).__name__}: {exc}"
        print("QWEN_LOAD_ERROR " + engine.error, flush=True)
        return 1
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
