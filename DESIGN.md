# Purr View — Design & Roadmap

> **Status: paused.** Working, but not performance-tuned. This document captures the
> plan for a future performance rewrite so it can be picked up without re-deriving
> everything. If you're just here to use it, see the [README](README.md).

## TL;DR of the plan

Stop making one full-resolution BGR frame do three jobs. Today a single decoded frame
feeds detection **and** the HUD/preview **and** recording, and every frame is decoded
and then re-encoded (twice). The target design splits those consumers so each gets the
cheapest form it needs, lets **ffmpeg** own the camera, and records via segment files
instead of per-frame `VideoWriter` calls in Python.

- **Recording:** one long-lived ffmpeg process → continuous H.264 segments on `/dev/shm`
  → concat on motion trigger. No per-frame Python, no double encode.
- **Detection:** a small **grayscale** stream (not full BGR) feeds the existing MOG2
  detector, unchanged.
- **Preview/HUD:** HUD moves to the live preview only (can't burn overlays into a
  stream-copied recording). Stream JPEG encoded **once per camera** and fanned out to
  all viewers, not re-encoded per client.
- **Hardware:** migrate the target from **Pi Zero 2 W (512 MB — too tight)** to
  **Pi 4 (2–4 GB)**, which still has the hardware H.264 encoder that the Pi 5 lacks.

---

## Why the current pipeline is inefficient

Per camera, per frame, all on one thread in [`cam_worker`](src/cam.py) (~L229):

1. **Decode.** The USB cam sends MJPG; `cap.read()` ([src/cam.py](src/cam.py) L235)
   decodes it to a full BGR array (software JPEG decode) — every frame.
2. **Detection throws most of it away.** [`motion_percent_mog2`](src/cam.py) (L171–188)
   immediately converts BGR→gray and downscales, so MOG2 only ever sees a small
   grayscale image. The full BGR frame is not a requirement of detection.
3. **Double encode.** During motion the frame is encoded to `*_temp.mp4` with `mp4v`
   ([src/cam.py](src/cam.py) L336–341, L368). Then
   [`post_process_video`](src/cam.py) (L97–142) **re-opens that temp file, decodes every
   frame** (L127) **and re-encodes** it into the final `.mp4` just to prepend the
   pre-buffer. Every recording is encoded twice, with a generation of quality loss.
4. **Per-client stream encode.** [`_mjpeg_gen`](src/view.py) (L79–111) calls
   `cv2.imencode` **independently per connected client** (L102), so N viewers of one
   camera = N encodes of the identical frame, every frame.
5. **In-RAM pre-buffer is huge.** The pre-buffer holds raw BGR frames
   ([src/cam.py](src/cam.py) L198, L321): at 720p that's ~2.6 MB/frame, so a 3 s buffer
   at 20 fps ≈ ~158 MB — fatal on a 512 MB device.

On a Pi 5 with spare cores this is invisible. On constrained hardware the decode +
double-encode round trip is exactly what doesn't fit.

---

## Target architecture

### 1. Recording: ffmpeg segments + concat-copy (steal from `voice-pilot.py`)

One long-lived ffmpeg process reads the camera and writes fixed-length segments
(`.ts`, e.g. 2 s) to a tmpfs (`/dev/shm`). A monitor loop keeps a rolling window of
recent segments and deletes old ones. On a motion trigger, select the segments covering
`pre-buffer + event + post-buffer` and concatenate them.

This is exactly the pattern in the reference project's `ffmpegStream` /
`videoSegmentMonitoring` / `processAndUploadVideo` (segment muxer + concat demuxer with
`-c copy`). Benefits: no per-frame Python, pre/post buffer is compressed segments on
disk (a few MB, not ~158 MB of BGR), and recording becomes cheap.

**USB MJPG caveat:** a USB MJPG cam has no native H.264 to `-c copy`. So one encode is
unavoidable — but do it **once, in hardware**: ffmpeg `-c:v h264_v4l2m2m` on a Pi 4.
That's a single HW encode instead of Python's two software encodes.

**Keyframe caveat:** `-c copy` segmenting cuts on keyframes, so segment boundaries are
approximate. Make the encoder emit frequent keyframes (GOP ≤ segment length) for clean
pre-buffer granularity.

### 2. Detection: a cheap grayscale stream, decoupled from recording resolution

Detection needs a small grayscale image, not full BGR — keep the current MOG2 logic and
`downscale: 2` tuning, just change where the frames come from:

- **Single USB cam (current):** let the one ffmpeg process fan out — HW-encode H.264
  segments to disk **and** pipe a tiny `scale=…,format=gray` stream to stdout for the
  Python detector. The MJPG decode happens once inside ffmpeg; Python never handles a
  BGR array.
- **If a CSI camera is ever used:** picamera2 gives a `lores` YUV stream (the Y plane
  *is* grayscale) alongside a HW-H.264 main stream — detection becomes nearly free.
  picamera2's `CircularOutput` is purpose-built for motion pre-roll recording.

Detection resolution is now a quality knob, not a CPU knob — 640×360 is fine to keep.

### 3. Preview / HUD

`-c copy` can't draw pixels, so the burned-in HUD moves to the **live preview only**.
For the browser stream: encode each camera's JPEG **once** (in one place, at the
`HTTP_FPS_LIMITER` rate), publish the bytes to a shared slot, and have every client
generator yield the latest bytes — gated on an active-viewer count so idle cameras don't
encode. Optionally downscale / lower quality / lower fps for the preview.

---

## Hardware decision

| Board | HW H.264 encode | RAM | Verdict |
|---|---|---|---|
| Pi Zero 2 W | ✅ | 512 MB | Encoder fine, **RAM is the wall** — original target, too tight |
| Pi 4 (2–4 GB) | ✅ (`h264_v4l2m2m`, `/dev/video11`) | 2/4/8 GB | **Chosen target** — comfortable |
| Pi 5 | ❌ (removed) | 4/8 GB | Strong CPU but must software-encode |
| x86 mini-PC (N100 / used micro) | ✅ QuickSync/VAAPI | 8–16 GB | Best "any Linux + Docker" home if not Pi |

**Decision:** target the **Pi 4 (2 GB minimum)**. It has the HW encoder and enough RAM,
turning the whole project from "fighting the hardware" into "comfortable." An x86
mini-PC with QuickSync is the better base if the goal shifts to a portable Docker tool.

---

## Docker notes

For a single app on a dedicated device, Docker's value is **build/distribution
reproducibility**, not runtime (the daemon is overhead). If dockerized:

- USB cam: pass `--device /dev/video0` (and the metadata node if present).
- HW encode: pass `--device /dev/video11` (bcm2835-codec) and ensure the container's
  ffmpeg is built with `h264_v4l2m2m`.
- Build multi-arch (arm64) images; develop on a stronger box, ship the same image.
- On x86, QuickSync needs `/dev/dri` passthrough + VAAPI-enabled ffmpeg.

---

## Migration plan (incremental — old code keeps running)

Refactor, don't rewrite. Changes are concentrated in `cam.py` + a new `recorder.py`;
motion detection, config, upload, Flask viewer, deploy scripts, and signal handling all
survive.

- [ ] **0. Hardware spike first.** On the real target device, a throwaway script:
      ffmpeg → 2 s `.ts` segments to `/dev/shm` (+ a `format=gray` pipe for USB), a
      rolling-delete loop, concat-copy on a fake trigger. Watch `htop` + `df /dev/shm`.
      Confirm 720p20 holds and CPU/RAM are comfortable **before** touching the app.
- [ ] **1. `recorder.py`.** Turn the spike into a module: start(), rolling segment
      buffer + cleanup, `save_clip(start, end)` (concat-copy). Adapt from
      `voice-pilot.py`'s segment/monitor/concat functions.
- [ ] **2. Detection source.** Feed the grayscale pipe/lores stream into the existing
      `motion_percent_mog2` — no change to the detector or its tuning.
- [ ] **3. Rewire `cam_worker`.** Replace "open writer on motion → write frames →
      post-process re-encode" with "on motion, `recorder.save_clip(window)`." Keep the
      state machine. Note: recording is now always-on buffering; the trigger just
      selects a time window (simpler — no opening/closing writers mid-event).
- [ ] **4. Viewer.** Fix the preview frame source; encode JPEG once + fan out; gate on
      viewer count; optionally downscale the preview.
- [ ] **5. Cleanup.** Remove the temp-file/double-encode path; update `config.json`
      (segment length, buffer window) and `install.sh` (ffmpeg dependency).

Each step is independently testable; there's never a period where nothing works.

---

## Open questions / decisions to revisit

- **Camera:** stay on USB MJPG (one HW encode), or move to CSI (picamera2, cheapest) or
  IP/RTSP (pure `-c copy`)? This is the biggest lever — it decides whether recording is
  zero-encode or one-encode.
- **HUD in recordings:** confirmed dropped to preview-only? If a burned-in timestamp is
  truly required, that reintroduces a decode→draw→encode pass and changes the design.
- **Deploy:** systemd (lighter, current) vs Docker (reproducible, heavier). Pick per
  whether distribution matters.

---

## Background

Built because [`motion`](https://motion-project.github.io/) didn't give enough control
over configuration and a custom on-frame HUD. For a mature, lightweight alternative see
`motion` + [motionEye](https://github.com/motioneye-project/motioneye); for ML object
detection see [Frigate](https://frigate.video/).
