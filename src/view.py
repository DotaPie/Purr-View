# view.py
import time
from threading import Thread
import cv2
from flask import Flask, Response, render_template_string, abort
from werkzeug.serving import make_server

INDEX_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Purr View</title>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <style>
    :root { color-scheme: light dark; }
    body { margin:0; background:Canvas; color:CanvasText;
           font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; }
    .grid {
      display:grid;
      grid-template-columns: repeat(auto-fit, minmax(640px, 1fr));
      gap:16px; padding:16px;
    }
    .card { border-radius:12px; overflow:hidden; box-shadow:0 2px 10px rgba(0,0,0,.12); }
    .frame {
      display:block;
      width:100%;         
      height:auto;        
      background:#111;    
    }
  </style>
</head>
<body>
  <main class="grid">
    {% for c in cams %}
      <div class="card">
        <img class="frame"
             src="/stream/{{ c.idx }}"
             alt="cam {{ c.idx }}"
             width="{{ c.width }}" height="{{ c.height }}" />
      </div>
    {% endfor %}
  </main>
</body>
</html>
"""

class Viewer:
    def __init__(self, current_frame, cam_count, camera_configs, stop_event, host="0.0.0.0", port=5000, http_fps_limit=0):
        self.current_frame = current_frame
        self.cam_count = int(cam_count)
        self.camera_configs = camera_configs
        self.stop_event = stop_event
        self.host = host
        self.port = port
        self.http_fps_limit = int(http_fps_limit)  # 0 = unlimited

        self.app = Flask(__name__)
        self._server = None
        self._thread = None
        self._bind_routes()

    def _mjpeg_gen(self, cam_idx: int):
        boundary = b"--frame"
        # compute min_dt from limiter; if 0 or <1, treat as unlimited
        target_fps = self.http_fps_limit if self.http_fps_limit and self.http_fps_limit > 0 else None
        min_dt = (1.0 / float(target_fps)) if target_fps else 0.0
        last_sent = 0.0

        try:
            while not self.stop_event.is_set():
                frame = self.current_frame[cam_idx]
                if frame is None:
                    time.sleep(0.01)
                    continue

                if target_fps:
                    now = time.time()
                    dt = now - last_sent
                    if dt < min_dt:
                        # sleep just enough to hit the target cadence
                        time.sleep(max(0.0, min_dt - dt))
                        continue
                    last_sent = now

                ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if not ok:
                    time.sleep(0.01)
                    continue

                yield (boundary + b"\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" +
                    jpg.tobytes() + b"\r\n")
        except (GeneratorExit, BrokenPipeError):
            pass  # client closed

    def _bind_routes(self):
        app = self.app
        _mjpeg_gen = self._mjpeg_gen

        @app.get("/stream/<int:cam_idx>")
        def stream(cam_idx: int):
            if cam_idx < 0 or cam_idx >= self.cam_count:
                abort(404)
            resp = Response(
                _mjpeg_gen(cam_idx),
                mimetype="multipart/x-mixed-replace; boundary=frame",
            )
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return resp

        @app.get("/")
        def index():
            cams = []
            for i in range(min(self.cam_count, 4)):
                cfg = self.camera_configs[i]
                cams.append({
                    "idx": i,
                    "width": int(cfg["FRAME_WIDTH"]),
                    "height": int(cfg["FRAME_HEIGHT"]),
                })
            return render_template_string(INDEX_HTML, cams=cams)

    # ---- lifecycle ----
    def start(self):
        if self._server is not None:
            return
        # IMPORTANT: threaded=True so multiple MJPEG streams work concurrently
        self._server = make_server(self.host, self.port, self.app, threaded=True)
        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self, timeout: float | None = 5.0):
        if self._server is None:
            return
        try:
            self._server.shutdown()
        finally:
            if self._thread is not None:
                self._thread.join(timeout=timeout)
        self._server = None
        self._thread = None
