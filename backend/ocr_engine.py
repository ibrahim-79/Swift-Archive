import os
import time
import sys
from pathlib import Path
import fitz  # PyMuPDF
from PIL import Image
from rapidocr_onnxruntime import RapidOCR
from docx import Document as DocxDocument
import numpy as np

# Initialize RapidOCR once (lazy singleton)
# Uses PaddleOCR models via ONNX Runtime — no PaddlePaddle dependency needed
_ocr_instance = None

# Performance knobs (easy to edit later):
# - CPU_THREAD_LIMIT controls how many CPU threads ONNX/OpenMP will try to use.
#   Keeping this low reduces CPU usage / fan noise at the cost of slower OCR.
# - Prefer GPU (CUDA) when available. Requires installing onnxruntime-gpu.
CPU_THREAD_LIMIT = int(os.getenv("OCR_CPU_THREADS", "0"))

# Rendering scanned PDF pages at high DPI increases CPU/RAM a lot.
# Lower DPI is faster and uses less memory, but may reduce OCR accuracy.
PDF_OCR_DPI = int(os.getenv("OCR_PDF_DPI", "150"))
OCR_REQUIRE_CUDA = os.getenv("OCR_REQUIRE_CUDA", "0") == "1"


def _apply_thread_limits():
    # These environment variables are read by OpenMP/BLAS/ONNXRuntime to size thread pools.
    # Set them BEFORE creating the OCR model/session.
    if CPU_THREAD_LIMIT and CPU_THREAD_LIMIT > 0:
        limit = str(CPU_THREAD_LIMIT)
    else:
        # Default: roughly 50% of logical CPU cores.
        cores = os.cpu_count() or 2
        limit = str(max(1, cores // 2))

    os.environ.setdefault("OMP_NUM_THREADS", limit)
    os.environ.setdefault("OPENBLAS_NUM_THREADS", limit)
    os.environ.setdefault("MKL_NUM_THREADS", limit)
    os.environ.setdefault("NUMEXPR_NUM_THREADS", limit)
    os.environ.setdefault("VECLIB_MAXIMUM_THREADS", limit)
    os.environ.setdefault("ONNXRUNTIME_THREADPOOL_SIZE", limit)


def _pick_onnx_providers():
    # Check available providers from ONNX Runtime.
    try:
        import onnxruntime as ort
        available = set(ort.get_available_providers())
        return available
    except Exception:
        return set()


def _get_module_session_providers(module_obj):
    """Best-effort helper for RapidOCR internal module session provider introspection."""
    # Different modules expose the OrtInferSession differently:
    # - TextDetector/TextClassifier: module.infer.session
    # - TextRecognizer: module.session
    if hasattr(module_obj, "infer") and hasattr(module_obj.infer, "session"):
        session_obj = module_obj.infer.session
        if hasattr(session_obj, "get_providers"):
            return session_obj.get_providers()
        if hasattr(session_obj, "session") and hasattr(session_obj.session, "get_providers"):
            return session_obj.session.get_providers()
    if hasattr(module_obj, "session"):
        session_obj = module_obj.session
        if hasattr(session_obj, "get_providers"):
            return session_obj.get_providers()
        if hasattr(session_obj, "session") and hasattr(session_obj.session, "get_providers"):
            return session_obj.session.get_providers()
    return []


def _add_windows_cuda_dll_paths():
    """Add common NVIDIA wheel DLL folders to PATH search on Windows.

    Helps ORT find cudnn/cuda DLLs when installed via pip wheels.
    """
    if os.name != "nt" or not hasattr(os, "add_dll_directory"):
        return

    site_pkg = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    candidate_bins = [
        site_pkg / "cudnn" / "bin",
        site_pkg / "cublas" / "bin",
        site_pkg / "cuda_runtime" / "bin",
        site_pkg / "cuda_nvrtc" / "bin",
    ]
    for p in candidate_bins:
        if p.exists():
            try:
                os.add_dll_directory(str(p))
            except Exception:
                pass

    # Optional manual override (semicolon-separated absolute paths).
    # Example:
    #   OCR_EXTRA_DLL_DIRS=C:\path\to\torch\lib;C:\path\to\cudnn\bin
    extra_dirs = os.getenv("OCR_EXTRA_DLL_DIRS", "").strip()
    if extra_dirs:
        for raw in extra_dirs.split(";"):
            p = raw.strip()
            if not p:
                continue
            try:
                if Path(p).exists():
                    os.add_dll_directory(p)
            except Exception:
                pass


def get_ocr() -> RapidOCR:
    global _ocr_instance
    if _ocr_instance is None:
        _apply_thread_limits()
        _add_windows_cuda_dll_paths()

        # Check available providers for logging/decision.
        available = _pick_onnx_providers()

        # RapidOCR expects module-specific CUDA flags.
        # Passing only `use_cuda=True` is not enough for all versions/config parsing.
        use_cuda = "CUDAExecutionProvider" in available

        print(f"[OCR] Available providers: {available}")
        print(f"[OCR] use_cuda={use_cuda}")

        if use_cuda:
            _ocr_instance = RapidOCR(
                det_use_cuda=True,
                cls_use_cuda=True,
                rec_use_cuda=True,
            )
            print("[OCR] Initialized with CUDA GPU support")

            # Verify actual providers used by each model session.
            try:
                det_providers = _get_module_session_providers(_ocr_instance.text_det)
                cls_providers = _get_module_session_providers(_ocr_instance.text_cls)
                rec_providers = _get_module_session_providers(_ocr_instance.text_rec)

                print(f"[OCR] Detection model providers: {det_providers}")
                print(f"[OCR] Classifier model providers: {cls_providers}")
                print(f"[OCR] Recognition model providers: {rec_providers}")

                first = [
                    det_providers[0] if det_providers else "",
                    cls_providers[0] if cls_providers else "",
                    rec_providers[0] if rec_providers else "",
                ]
                print(f"[OCR] First provider - Det/Cls/Rec: {first}")

                if not any("CUDA" in p for p in first):
                    msg = (
                        "[OCR] WARNING: CUDA not actually being used. "
                        "Check CUDA 12 + cuDNN 9 DLLs (cudnn64_9.dll) and PATH."
                    )
                    print(msg)
                    if OCR_REQUIRE_CUDA:
                        raise RuntimeError(msg)
            except Exception as e:
                print(f"[OCR] Could not verify session providers: {e}")
                if OCR_REQUIRE_CUDA:
                    raise
        else:
            _ocr_instance = RapidOCR()
            print("[OCR] Initialized with CPU only")
    return _ocr_instance


# File type categories
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp", ".gif"}
PDF_EXTENSIONS = {".pdf"}
DOCX_EXTENSIONS = {".docx"}
TEXT_EXTENSIONS = {".txt", ".csv", ".log", ".md", ".json", ".xml", ".html", ".htm"}


def classify_file(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    elif ext in PDF_EXTENSIONS:
        return "pdf"
    elif ext in DOCX_EXTENSIONS:
        return "docx"
    elif ext in TEXT_EXTENSIONS:
        return "text"
    return "unknown"


def extract_text_from_text_file(file_path: str) -> dict:
    """Direct text extraction — no OCR needed."""
    start = time.time()
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    elapsed = int((time.time() - start) * 1000)
    return {
        "ocr_performed": False,
        "confidence_score": 1.0,
        "extracted_text": text,
        "ocr_details": [],
        "processing_time_ms": elapsed,
    }


def extract_text_from_docx(file_path: str) -> dict:
    """Extract text from .docx — no OCR needed."""
    start = time.time()
    doc = DocxDocument(file_path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    text = "\n".join(paragraphs)
    elapsed = int((time.time() - start) * 1000)
    return {
        "ocr_performed": False,
        "confidence_score": 1.0,
        "extracted_text": text,
        "ocr_details": [],
        "processing_time_ms": elapsed,
    }


def extract_text_from_image(file_path: str) -> dict:
    """Run OCR on an image file via RapidOCR (ONNX Runtime)."""
    start = time.time()
    ocr = get_ocr()
    result, _ = ocr(file_path)

    lines = []
    details = []
    confidences = []

    if result:
        for item in result:
            bbox = item[0]
            text = item[1]
            try:
                conf = float(item[2])
            except (TypeError, ValueError):
                conf = 0.0
            lines.append(text)
            confidences.append(conf)
            details.append({
                "text": text,
                "confidence": round(conf, 4),
                "bbox": [list(pt) for pt in bbox] if bbox else [],
            })

    avg_confidence = round(sum(confidences) / len(confidences), 4) if confidences else 0.0
    elapsed = int((time.time() - start) * 1000)

    return {
        "ocr_performed": True,
        "confidence_score": avg_confidence,
        "extracted_text": "\n".join(lines),
        "ocr_details": details,
        "processing_time_ms": elapsed,
    }


def extract_text_from_pdf(file_path: str) -> dict:
    """Extract text from PDF. Uses native text first; falls back to OCR for scanned pages."""
    start = time.time()
    doc = fitz.open(file_path)

    all_text = []
    ocr_performed = False
    confidences = []
    details = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text().strip()

        if text:
            # Native text found — no OCR needed for this page
            all_text.append(text)
            confidences.append(1.0)
        else:
            # Scanned page — render to image and OCR
            ocr_performed = True
            pix = page.get_pixmap(dpi=PDF_OCR_DPI)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            img_np = np.array(img)

            ocr = get_ocr()
            result, _ = ocr(img_np)

            if result:
                for item in result:
                    txt = item[1]
                    try:
                        conf = float(item[2])
                    except (TypeError, ValueError):
                        conf = 0.0
                    all_text.append(txt)
                    confidences.append(conf)
                    details.append({
                        "text": txt,
                        "confidence": round(conf, 4),
                        "bbox": [list(pt) for pt in item[0]] if item[0] else [],
                        "page": page_num + 1,
                    })

    doc.close()
    avg_confidence = round(sum(confidences) / len(confidences), 4) if confidences else 0.0
    elapsed = int((time.time() - start) * 1000)

    return {
        "ocr_performed": ocr_performed,
        "confidence_score": avg_confidence,
        "extracted_text": "\n".join(all_text),
        "ocr_details": details,
        "processing_time_ms": elapsed,
    }


def process_file(file_path: str, filename: str) -> dict:
    """Main entry point: classify file and extract text accordingly."""
    file_type = classify_file(filename)

    if file_type == "image":
        return extract_text_from_image(file_path)
    elif file_type == "pdf":
        return extract_text_from_pdf(file_path)
    elif file_type == "docx":
        return extract_text_from_docx(file_path)
    elif file_type == "text":
        return extract_text_from_text_file(file_path)
    else:
        return {
            "ocr_performed": False,
            "confidence_score": 0.0,
            "extracted_text": "",
            "ocr_details": [],
            "processing_time_ms": 0,
        }
