### LOGGING ###
from logging_setup import get_logger
logger = get_logger()

### IMPORTS ###
import os
import threading
import json
import time
from pathlib import Path
import signal
from cam import CameraManager
from view import Viewer
from utils import init_storage_in_ram, monitor_resources_usages

### CONF ###
with open(os.path.join(os.path.dirname((os.path.abspath(__file__))), "config.json"), "r") as f:
    config = json.load(f)

VIDEO_PATH_IN_RAM = "/dev/shm/PurrView/videos"

LOGGING_LEVEL = config["LOGGING_LEVEL"]
FTP_UPLOAD_VIDEO = config["FTP_UPLOAD_VIDEO"]
VIDEO_PATH = Path(os.path.expandvars(config["VIDEO_PATH"])).expanduser() # deals with $USER and ~/...
SAVE_VIDEO_LOCALLY = config["SAVE_VIDEO_LOCALLY"]
MAX_CONCURRENT_VIDEO_WRITES_AND_UPLOADS = config["MAX_CONCURRENT_VIDEO_WRITES_AND_UPLOADS"]
HTTP_SERVER_ENABLED = config["HTTP_SERVER_ENABLED"]
HTTP_SERVER_PORT = config["HTTP_SERVER_PORT"]
HTTP_FPS_LIMITER = config["HTTP_FPS_LIMITER"]

### GLOBALS ###
stop_event = threading.Event()

### FUNCTIONS ###

def main():
    logger.info("")
    logger.info("")
    logger.info(f"[SYS] Init")
    os.makedirs(VIDEO_PATH, exist_ok=True)

    if LOGGING_LEVEL == "DEBUG":
        resource_usage_monitor_t = None

    def shutdown(signum, frame):
        logger.info(f"[SYS] Signal {signum} received ({frame}) - shutting down")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, shutdown)

    # Initialize camera manager
    camera_manager = CameraManager(
        stop_event=stop_event,
        max_concurrent_workers=MAX_CONCURRENT_VIDEO_WRITES_AND_UPLOADS,
        ftp_upload_video=FTP_UPLOAD_VIDEO,
        save_video_locally=SAVE_VIDEO_LOCALLY,
        video_path=VIDEO_PATH
    )
    
    try:
        camera_manager.init_cameras()
        init_storage_in_ram(VIDEO_PATH_IN_RAM)
        
        # Start camera threads
        camera_manager.start_camera_threads()

        if LOGGING_LEVEL == "DEBUG":
            resource_usage_monitor_t = threading.Thread(target=monitor_resources_usages, args=(stop_event,))
            resource_usage_monitor_t.start()

        if HTTP_SERVER_ENABLED:
            # Start viewer HTTP server (non-blocking)
            viewer = Viewer(
                current_frame=camera_manager.get_current_frames(),
                cam_count=camera_manager.get_camera_count(),
                camera_configs=camera_manager.get_camera_configs(),
                stop_event=stop_event,
                host="0.0.0.0",
                port=HTTP_SERVER_PORT,
                http_fps_limit=HTTP_FPS_LIMITER
            )
            viewer.start()
            logger.info(f"[SYS] HTTP server started on 0.0.0.0:{HTTP_SERVER_PORT}")

        # main wait loop; exits when signal handler sets the event
        while not stop_event.is_set():
            time.sleep(1)

    except Exception:
        logger.exception(f"[SYS] Unexpected exception detected")

    finally:
        logger.info("[SYS] Starting thread cleanup ...")

        # stop server
        if HTTP_SERVER_ENABLED:
            viewer.stop()

        # stop RAM monitor
        if LOGGING_LEVEL == "DEBUG":
            try:
                logger.info("[SYS] Joining CPU/RAM monitoring ...")
                resource_usage_monitor_t.join()
                
            except Exception as e:
                logger.warning(f"[SYS] CPU/RAM monitor cleanup issue ({repr(e)})")

        # join cam workers
        camera_manager.join_camera_threads()

        # shutdown camera manager (including video upload executor)
        camera_manager.shutdown_executor()

        logger.info("[SYS] Cleanup completed")

    return 0

if __name__ == "__main__":
    # propagate exit code from main()
    raise SystemExit(main())