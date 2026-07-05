import logging
import io
import zipfile
import xml.etree.ElementTree as ET

def parse_pdf(file_bytes: bytes) -> str:
    """Extract text from PDF file bytes using PyPDF2."""
    text = ""
    try:
        # Import PyPDF2 locally to avoid startup dependencies
        import PyPDF2
        reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    except Exception as e:
        logging.info(f"[CV-Parser] PDF parsing error: {e}")
    return text.strip()

def parse_docx(file_bytes: bytes) -> str:
    """Extract text from Word Document (DOCX) file bytes using built-in zipfile XML parser."""
    text_parts = []
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as docx_zip:
            # Word document main body XML content
            xml_content = docx_zip.read('word/document.xml')
            root = ET.fromstring(xml_content)
            
            # Document namespace
            namespaces = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            
            # Find all paragraph tags
            for p in root.findall('.//w:p', namespaces):
                # Inside paragraph, find all text tags
                t_elements = p.findall('.//w:t', namespaces)
                p_text = "".join([t.text for t in t_elements if t.text])
                if p_text:
                    text_parts.append(p_text)
                    
    except Exception as e:
        logging.info(f"[CV-Parser] DOCX parsing error: {e}")
        
    return "\n".join(text_parts).strip()

def extract_cv_text(file_bytes: bytes, filename: str) -> str:
    """Extract raw text from a CV based on its file extension."""
    if not file_bytes:
        return ""
    
    fn_lower = filename.lower()
    if fn_lower.endswith('.pdf'):
        logging.info(f"[CV-Parser] Parsing PDF: {filename}")
        return parse_pdf(file_bytes)
    elif fn_lower.endswith('.docx') or fn_lower.endswith('.doc'):
        # Note: older .doc files are binary OLE, but if they are actually docx renamed, zip will succeed.
        # Fallback to docx zip parsing.
        logging.info(f"[CV-Parser] Parsing DOCX: {filename}")
        return parse_docx(file_bytes)
    else:
        # Fallback: treat as plain text if it's text-like
        try:
            return file_bytes.decode('utf-8', errors='ignore')
        except Exception:
            logging.info(f"[CV-Parser] Unsupported file format for: {filename}")
            return ""
