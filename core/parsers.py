"""
Document text extraction for RagLeap Core.
Supports .txt, .pdf, .docx — extracts plain text so core.ingest.ingest_document
can chunk/embed/store it exactly the same way regardless of source format.
"""
import io
import logging
import os

logger = logging.getLogger(__name__)

CORE_EXTENSIONS = {".txt", ".pdf", ".docx"}

try:  # optional: the ragleap-rag package adds the other document formats
    from ragleap import parsers as _rag_parsers
except Exception:  # not installed, or one of its own imports is missing
    _rag_parsers = None

SUPPORTED_EXTENSIONS = set(CORE_EXTENSIONS)
if _rag_parsers is not None:
    SUPPORTED_EXTENSIONS |= set(_rag_parsers.SUPPORTED_EXTENSIONS)


def extract_text(filename: str, raw_bytes: bytes) -> str:
    """
    Extract plain text from raw file bytes, dispatching on file extension.
    Raises ValueError for unsupported extensions or extraction failures.
    """
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    ext = f".{ext}"

    if ext == ".txt":
        return _extract_txt(raw_bytes)
    elif ext == ".pdf":
        return _extract_pdf(raw_bytes)
    elif ext == ".docx":
        return _extract_docx(raw_bytes)
    elif _rag_parsers is not None and ext in _rag_parsers.SUPPORTED_EXTENSIONS:
        return _rag_parsers.extract_text(filename, raw_bytes)
    else:
        raise ValueError(
            f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}."
        )


def _extract_txt(raw_bytes: bytes) -> str:
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        logger.warning("UTF-8 decode failed, retrying with latin-1")
        return raw_bytes.decode("latin-1")


def _extract_pdf(raw_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise ValueError("pypdf is required for PDF support — check requirements.txt") from e

    reader = PdfReader(io.BytesIO(raw_bytes))
    pages_text = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if text.strip():
            pages_text.append(text)
        else:
            logger.warning(f"No extractable text on PDF page {i + 1} (likely scanned/image-only)")

    full_text = "\n\n".join(pages_text)
    if not full_text.strip():
        raise ValueError(
            "No text could be extracted from this PDF. It may be a scanned "
            "image-only document, which requires OCR (not currently supported)."
        )
    return full_text


def _extract_docx(raw_bytes: bytes) -> str:
    try:
        import docx
    except ImportError as e:
        raise ValueError("python-docx is required for DOCX support — check requirements.txt") from e

    document = docx.Document(io.BytesIO(raw_bytes))
    paragraphs = [p.text for p in document.paragraphs if p.text.strip()]

    full_text = "\n\n".join(paragraphs)
    if not full_text.strip():
        raise ValueError("No text could be extracted from this DOCX file — it may be empty.")
    return full_text


def url_ingest_available() -> bool:
    """True when web pages can be added by address (needs ragleap-rag with its web support)."""
    if _rag_parsers is None:
        return False
    try:
        import inspect
        import trafilatura  # noqa: F401
        from ragleap import web as _web
        from ragleap._net import UnsafeURLError  # noqa: F401
        # an older package without the private-address check must never be used to fetch pages
        if "allow_private" not in inspect.signature(_web.fetch_url_text).parameters:
            return False
    except Exception:
        return False
    return True


def fetch_url_text(url: str) -> str:
    """
    Fetch a public web page and return its readable text. Addresses that resolve to private,
    loopback or link-local networks are refused (ValueError) unless the operator sets
    INGEST_ALLOW_PRIVATE_URLS=true in .env; a request can never switch that on. Raises ValueError
    when nothing readable is found and ImportError when the web support is not installed.
    """
    if _rag_parsers is None:
        raise ImportError("Adding web pages needs the ragleap-rag package.")
    from ragleap.web import fetch_url_text as _fetch
    allow_private = os.environ.get("INGEST_ALLOW_PRIVATE_URLS", "").strip().lower() == "true"
    text = _fetch(url, allow_private=allow_private)
    if not text or not text.strip():
        raise ValueError("Could not extract readable text from that address.")
    return text
