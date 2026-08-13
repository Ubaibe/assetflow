import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Optional


class DocumentProcessingError(Exception):
    pass


@dataclass
class DocumentProcessingResult:
    document_type: str
    processing_mode: str
    extracted_text: Optional[str] = None
    original_mime_type: str = ""
    metadata: dict = field(default_factory=dict)
    raw_bytes: Optional[bytes] = None
    error: Optional[str] = None


class DocumentProcessor:
    def __init__(self, max_upload_mb: int = 10):
        self.max_bytes = max_upload_mb * 1024 * 1024
        self.magic_signatures = {
            ".pdf": b"%PDF-",
            ".png": b"\x89PNG\r\n\x1a\n",
            ".jpg": b"\xff\xd8\xff",
            ".jpeg": b"\xff\xd8\xff",
        }
        self.allowed_mimes = {
            "application/pdf": {".pdf"},
            "image/png": {".png"},
            "image/jpeg": {".jpg", ".jpeg"},
        }

    def process(
        self,
        file_stream: BinaryIO,
        filename: str,
        content_type: str,
        max_bytes: Optional[int] = None,
    ) -> DocumentProcessingResult:
        if not file_stream or not filename:
            raise DocumentProcessingError("No file provided")

        if max_bytes is not None:
            self.max_bytes = max_bytes

        size = self._validate_size(file_stream)
        ext = self._validate_extension(filename)
        self._validate_mime(content_type, ext)
        self._validate_magic(file_stream, ext)

        if ext == ".pdf":
            return self._process_pdf(file_stream, content_type, size)
        return self._process_image(file_stream, content_type, size, ext)

    def _validate_size(self, file_stream: BinaryIO) -> int:
        file_stream.seek(0, 2)
        size = file_stream.tell()
        file_stream.seek(0)
        if size > self.max_bytes:
            raise DocumentProcessingError(
                f"File exceeds maximum size of {self.max_bytes} bytes"
            )
        if size == 0:
            raise DocumentProcessingError("Empty file")
        return size

    def _validate_extension(self, filename: str) -> str:
        ext = Path(filename).suffix.lower()
        if ext not in self.magic_signatures:
            raise DocumentProcessingError(f"Unsupported file extension: {ext}")
        return ext

    def _validate_mime(self, content_type: str, ext: str) -> None:
        allowed = self.allowed_mimes.get(content_type.lower())
        if not allowed or ext not in allowed:
            raise DocumentProcessingError(
                f"MIME type mismatch: expected {sorted(self.allowed_mimes.keys())}, got {content_type}"
            )

    def _validate_magic(self, file_stream: BinaryIO, ext: str) -> None:
        signature = self.magic_signatures[ext]
        header = file_stream.read(len(signature))
        if header != signature:
            raise DocumentProcessingError("File content does not match declared type")
        file_stream.seek(0)

    def _process_pdf(self, file_stream: BinaryIO, content_type: str, size: int) -> DocumentProcessingResult:
        try:
            from pypdf import PdfReader
            reader = PdfReader(file_stream)
            text_parts = []
            for page in reader.pages:
                try:
                    text = page.extract_text()
                    if text:
                        text_parts.append(text)
                except Exception:
                    continue

            extracted_text = "\n".join(text_parts).strip()

            if not extracted_text:
                file_stream.seek(0)
                return DocumentProcessingResult(
                    document_type="pdf",
                    processing_mode="vision",
                    original_mime_type=content_type,
                    metadata={"page_count": len(reader.pages), "size_bytes": size},
                    raw_bytes=file_stream.read(),
                )

            return DocumentProcessingResult(
                document_type="pdf",
                processing_mode="text",
                extracted_text=extracted_text,
                original_mime_type=content_type,
                metadata={"page_count": len(reader.pages), "size_bytes": size},
            )
        except ImportError as exc:
            raise DocumentProcessingError("PDF processing requires pypdf") from exc
        except Exception as exc:
            raise DocumentProcessingError(f"Failed to read PDF: {exc}") from exc

    def _process_image(self, file_stream: BinaryIO, content_type: str, size: int, ext: str) -> DocumentProcessingResult:
        try:
            from PIL import Image
            image = Image.open(file_stream)
            metadata = {
                "format": image.format,
                "mode": image.mode,
                "size_bytes": size,
                "width": image.width,
                "height": image.height,
            }
            file_stream.seek(0)
            return DocumentProcessingResult(
                document_type="image",
                processing_mode="vision",
                original_mime_type=content_type,
                metadata=metadata,
                raw_bytes=file_stream.read(),
            )
        except ImportError as exc:
            raise DocumentProcessingError("Image processing requires Pillow") from exc
        except Exception as exc:
            raise DocumentProcessingError(f"Failed to read image: {exc}") from exc
