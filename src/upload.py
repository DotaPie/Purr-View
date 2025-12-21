import os
import shutil
import ftplib
import json
from datetime import date
from pathlib import PurePosixPath
from datetime import datetime as dt
from logging_setup import get_logger

logger = get_logger()

# Load config
with open(os.path.join(os.path.dirname(__file__), "config.json"), "r") as f:
    config = json.load(f)

FTP_HOSTNAME = config["FTP_HOSTNAME"]
FTP_USERNAME = config["FTP_USERNAME"]
FTP_PASSWORD = config["FTP_PASSWORD"]
FTP_PATH = config["FTP_PATH"]
FTP_TIMEOUT = config["FTP_TIMEOUT"]


def _ftp_join_path(*parts) -> str:
    """Join path parts with forward slashes for FTP"""
    return "/".join(str(p).strip("/\\") for p in parts)


def _ensure_remote_dirs(ftp: ftplib.FTP, path: str) -> None:
    """Create remote directory structure if it doesn't exist"""
    original_cwd = ftp.pwd()
    try:
        for part in PurePosixPath(path).parts:
            if part == "/":
                continue
            try:
                ftp.mkd(part)                     # try to create this level
            except ftplib.error_perm as e:
                if not str(e).startswith("550"):  # 550 = already exists
                    raise                        # re-raise unexpected errors
            ftp.cwd(part)                        # descend into it
    finally:
        ftp.cwd(original_cwd)                    # restore working dir


def _ftp_upload_file(cam_name: str, full_file_path: str) -> None:
    """Upload a file to FTP server with automatic directory creation"""
    if full_file_path is None:
        raise ValueError("full_file_path must be provided")
    
    timestamp = dt.now().timestamp()

    # --- build remote paths -------------------------------------------------
    YYYY, MM, DD = date.today().strftime("%Y %m %d").split()
    remote_dir   = _ftp_join_path(FTP_PATH, YYYY, MM, DD)
    remote_file  = _ftp_join_path(remote_dir, os.path.basename(full_file_path))

    # --- connect and upload -------------------------------------------------
    with ftplib.FTP(FTP_HOSTNAME, FTP_USERNAME, FTP_PASSWORD, timeout=FTP_TIMEOUT) as ftp:
        ftp.encoding = "utf-8"

        # create YYYY/MM/DD under FTP_PATH if needed
        _ensure_remote_dirs(ftp, remote_dir)

        # transfer the file
        with open(full_file_path, "rb") as src:
            ftp.storbinary(f"STOR {remote_file}", src)
            duration_ms = (dt.now().timestamp() - timestamp) * 1000
            logger.info(f"[{cam_name}] Uploaded {remote_file} ({duration_ms:.3f} ms)")


def _save_file_locally(cam_name: str, full_file_path: str, local_path: str) -> None:
    """Copy file to local storage directory"""
    logger.info(f"[{cam_name}] Copying file {full_file_path} to {local_path} ...")
    shutil.copy2(full_file_path, os.path.join(local_path, os.path.basename(full_file_path)))


def upload_and_cleanup(cam_name: str, full_file_path: str, 
                      ftp_upload: bool, save_locally: bool, local_path: str) -> None:
    """Handle FTP upload, local storage, and cleanup of video file"""
    try:
        # FTP Upload
        if ftp_upload:
            try:
                _ftp_upload_file(cam_name, full_file_path)
            except Exception as e:
                logger.error(f"[{cam_name}] Failed to upload file {full_file_path} ({repr(e)})")

        # Local Storage
        if save_locally:
            try:
                _save_file_locally(cam_name, full_file_path, local_path)
            except Exception as e:
                logger.error(f"[{cam_name}] Failed to save file locally {full_file_path} ({repr(e)})")
        
        # Cleanup temp file
        logger.debug(f"[{cam_name}] Deleting file {full_file_path} ...")
        os.remove(full_file_path)
        
    except Exception as e:
        logger.error(f"[{cam_name}] Failed to process file {full_file_path} ({repr(e)})")
        # Clean up on error
        if full_file_path and os.path.exists(full_file_path):
            try:
                os.remove(full_file_path)
            except:
                pass