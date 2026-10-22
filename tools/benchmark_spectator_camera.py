"""Temporary-fixture benchmark. Never opens the game's real SpectatorLog."""
import argparse
import json
import math
from pathlib import Path
import sys
import tempfile
import threading
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from spectator_camera import HeadCamera
from camera_realtime import FramePacer


def benchmark(seconds=5):
    workspace = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="rfc_camera_bench_",dir=workspace) as folder:
        root = Path(folder)
        for side in ("blue","red","match"):
            (root/side).mkdir()
        blue,red = root/"blue/head_position.txt",root/"red/head_position.txt"
        blue.write_text("0 0 0 1.7 0 0 0 0 1")
        red.write_text("0 0 0 1.7 1.5 0 0 0 1")
        (root/"match/camera_input.txt").write_text("0 3 -4\t0 0 0 1\t75\tFalse\tFalse")
        (root/"match/round_number.txt").write_text("1")
        cancel = threading.Event()
        counts = {"inputs":0,"reads":0}
        def inputs():
            pacer = FramePacer(60)
            started = time.monotonic()
            try:
                while not cancel.is_set():
                    at = time.monotonic()-started
                    x = .25*math.sin(at*2)
                    blue.write_text(f"0 0 {x:.5f} 1.7 0 0 0 0 1")
                    red.write_text(f"0 0 {-x:.5f} 1.7 1.5 0 0 0 1")
                    counts["inputs"] += 1
                    pacer.wait(cancel)
            finally:
                pacer.close()
        def reader():
            pacer = FramePacer(60)
            try:
                while not cancel.is_set():
                    try:
                        (root/"match/camera_input.txt").read_text()
                        counts["reads"] += 1
                    except OSError:
                        pass
                    pacer.wait(cancel)
            finally:
                pacer.close()
        threads = [threading.Thread(target=inputs),threading.Thread(target=reader)]
        camera = HeadCamera()
        try:
            camera.start(root,"blue",realtime=True,look_opponent=True,comfort=True,position_ms=20,rotation_ms=40)
            for thread in threads:
                thread.start()
            time.sleep(seconds)
            pipeline = camera.pipeline
            metrics = pipeline.metrics()
            metrics.update(seconds=seconds,source_updates=counts["inputs"],simulated_reads=counts["reads"],
                           source_samples=camera.samples,last_write_ms=camera.last_write_ms,
                           error=str(pipeline.error) if pipeline.error else None)
            return metrics
        finally:
            cancel.set()
            for thread in threads:
                if thread.ident is not None:
                    thread.join(timeout=2)
            camera.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds",type=float,default=5)
    args = parser.parse_args()
    print(json.dumps(benchmark(max(1,min(30,args.seconds))),ensure_ascii=False,indent=2))
