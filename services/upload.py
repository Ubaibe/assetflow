import hashlib
import os
import uuid
from datetime import datetime
from pathlib import Path
from flask import current_app
from werkzeug.utils import secure_filename
from database.enums import DocumentStatus


ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}

MAGIC_SIGNATURES = {
    ".pdf": b"%PDF-",
    ".png": b"\x89PNG\r\n\x1a\n",
    ".jpg": b"\xff\xd8\xff",
    ".jpeg": b"\xff\xd8\xff",
}


class UploadError(Exception):
    pass


def _get_extension(filename: str) -> str:
    return Path(filename).suffix.lower()


def _validate_extension(filename: str) -> str:
    ext = _get_extension(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise UploadError(f"Unsupported file extension: {ext}")
    return ext


def _validate_mime(content_type: str, expected_ext: str) -> None:
    expected_mimes = {
        ".pdf": ["application/pdf"],
        ".png": ["image/png"],
        ".jpg": ["image/jpeg"],
        ".jpeg": ["image/jpeg"],
    }
    allowed = expected_mimes.get(expected_ext, [])
    if content_type not in allowed:
        raise UploadError(f"MIME type mismatch: expected {allowed}, got {content_type}")


def _validate_magic_bytes(file_stream, expected_ext: str) -> bytes:
    signature = MAGIC_SIGNATURES.get(expected_ext)
    if signature is None:
        raise UploadError(f"No magic signature defined for {expected_ext}")

    header = file_stream.read(len(signature))
    if header != signature:
        raise UploadError("File content does not match declared type")

    file_stream.seek(0)
    return header


def _hash_file(file_stream) -> str:
    sha256 = hashlib.sha256()
    for chunk in iter(lambda: file_stream.read(8192), b""):
        sha256.update(chunk)
    file_stream.seek(0)
    return sha256.hexdigest()


def _generate_stored_filename(extension: str) -> str:
    return f"{uuid.uuid4().hex}{extension}"


def _ensure_upload_dir() -> Path:
    upload_dir = Path(current_app.config["UPLOAD_DIR"])
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


def validate_and_save_upload(file_storage) -> tuple[Path, str, int, str]:
    if not file_storage or file_storage.filename == "":
        raise UploadError("No file provided")

    original_filename = secure_filename(file_storage.filename)
    if not original_filename:
        raise UploadError("Invalid filename")

    extension = _validate_extension(original_filename)

    max_bytes = current_app.config["MAX_UPLOAD_MB"] * 1024 * 1024
    file_storage.seek(0, 2)
    file_size = file_storage.tell()
    file_storage.seek(0)

    if file_size > max_bytes:
        raise UploadError(f"File exceeds maximum size of {current_app.config['MAX_UPLOAD_MB']}MB")

    content_type = file_storage.content_type or "application/octet-stream"
    _validate_mime(content_type, extension)
    _validate_magic_bytes(file_storage, extension)
    file_hash = _hash_file(file_storage)

    upload_dir = _ensure_upload_dir()
    stored_filename = _generate_stored_filename(extension)
    destination = upload_dir / stored_filename

    file_storage.save(str(destination))

    return destination, original_filename, file_size, file_hash
