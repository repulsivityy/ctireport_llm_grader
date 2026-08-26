import io
import re
from typing import Tuple, Optional
from pypdf import PdfReader


class DocumentParsingError(Exception):
    """Custom exception raised when document parsing fails."""
    pass


def sanitize_report_text(text: str) -> str:
    """
    Sanitizes untrusted text to prevent XML boundary escape / tag smuggling attacks.
    Neutralizes system delimiter tags while preserving the actual textual meaning.
    """
    if not text:
        return ""
    
    # Neutralize sandbox delimiter tags
    sanitized = text.replace("</student_submission>", "&lt;/student_submission&gt;")
    sanitized = sanitized.replace("<student_submission>", "&lt;student_submission&gt;")
    sanitized = sanitized.replace("</initial_evaluation>", "&lt;/initial_evaluation&gt;")
    sanitized = sanitized.replace("<initial_evaluation>", "&lt;initial_evaluation&gt;")
    sanitized = sanitized.replace("<![CDATA[", "&lt;![CDATA[")
    sanitized = sanitized.replace("]]>", "]]&gt;")
    
    # Remove null bytes or non-printable ASCII control characters (keep newlines/tabs)
    sanitized = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', sanitized)
    
    return sanitized.strip()


def extract_text_from_bytes(file_bytes: bytes, filename: str) -> Tuple[str, str]:
    """
    Extracts text content from uploaded file bytes.
    Allowed Formats: PDF (.pdf), Markdown (.md), and Plain Text (.txt).

    Returns:
        Tuple of (sanitized_extracted_text, file_type_detected)
    """
    lower_name = filename.lower()
    
    if lower_name.endswith(".pdf"):
        raw_text = extract_text_from_pdf(file_bytes)
        return sanitize_report_text(raw_text), "pdf"
    elif lower_name.endswith((".md", ".markdown")):
        raw_text = extract_text_from_text_bytes(file_bytes)
        return sanitize_report_text(raw_text), "markdown"
    elif lower_name.endswith((".txt", ".text", ".log")):
        raw_text = extract_text_from_text_bytes(file_bytes)
        return sanitize_report_text(raw_text), "text"
    else:
        raise DocumentParsingError(
            f"Unsupported file format: '{filename}'. Only PDF (.pdf), Markdown (.md), or Text (.txt) files are accepted."
        )


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extracts text from PDF bytes using pypdf."""
    try:
        pdf_stream = io.BytesIO(file_bytes)
        reader = PdfReader(pdf_stream)
        
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                raise DocumentParsingError("The uploaded PDF is password-protected and cannot be read.")
        
        extracted_pages = []
        for idx, page in enumerate(reader.pages):
            page_text = page.extract_text()
            if page_text:
                extracted_pages.append(f"--- Page {idx + 1} ---\n{page_text.strip()}")
        
        full_text = "\n\n".join(extracted_pages).strip()
        if not full_text:
            raise DocumentParsingError(
                "No readable text could be extracted from this PDF. It might be a scanned image without OCR."
            )
        return full_text
    except DocumentParsingError:
        raise
    except Exception as e:
        raise DocumentParsingError(f"Failed to parse PDF document: {str(e)}")


def extract_text_from_text_bytes(file_bytes: bytes) -> str:
    """Decodes plain text or markdown bytes using standard encodings."""
    encodings = ["utf-8", "utf-8-sig", "latin-1", "cp1252"]
    for enc in encodings:
        try:
            text = file_bytes.decode(enc).strip()
            if text:
                return text
        except UnicodeDecodeError:
            continue
    raise DocumentParsingError("Unable to decode text file. Ensure it is encoded in valid UTF-8 or ASCII.")


def validate_report_content(content: str, min_chars: int = 80, max_chars: int = 250_000) -> Tuple[bool, Optional[str]]:
    """
    Validates report content length before sending to the LLM Judge.
    """
    cleaned = content.strip()
    if len(cleaned) < min_chars:
        return False, f"Report content is too short ({len(cleaned)} characters). A minimum of {min_chars} characters is required for evaluation."
    if len(cleaned) > max_chars:
        return False, f"Report content exceeds maximum limit ({len(cleaned):,} characters). Please trim below {max_chars:,} characters."
    return True, None
