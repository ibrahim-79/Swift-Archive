import os
import shutil
import queue
import threading
import time
import uuid
from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from database import init_db, insert_document, search_documents, get_all_documents, get_document_by_id, delete_document, get_document_count
from ocr_engine import process_file, classify_file

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI(title="OCR Archive System", version="1.0.0")

# Background queue to avoid processing many files in parallel.
# This keeps CPU/RAM usage stable when uploading lots of images.
JOB_WORKERS = int(os.getenv("OCR_JOB_WORKERS", "1"))
QUEUE_POLL_SLEEP_SEC = float(os.getenv("OCR_QUEUE_POLL_SLEEP_SEC", "0.1"))

_job_queue: "queue.Queue[dict]" = queue.Queue()
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_workers_started = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve uploaded files
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


@app.on_event("startup")
def startup():
    init_db()
    _start_workers()


def _start_workers():
    global _workers_started
    if _workers_started:
        return
    _workers_started = True

    count = max(1, JOB_WORKERS)
    for i in range(count):
        t = threading.Thread(target=_worker_loop, name=f"ocr-worker-{i}", daemon=True)
        t.start()


def _safe_filename(original: str) -> str:
    # Very small safety: strip path parts and replace spaces.
    name = os.path.basename(original or "")
    return name.replace(" ", "_")


def _save_upload_to_disk(file: UploadFile) -> tuple[str, str]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    safe_name = _safe_filename(file.filename)
    dest_path = os.path.join(UPLOAD_DIR, safe_name)

    base, ext = os.path.splitext(safe_name)
    counter = 1
    while os.path.exists(dest_path):
        dest_path = os.path.join(UPLOAD_DIR, f"{base}_{counter}{ext}")
        safe_name = f"{base}_{counter}{ext}"
        counter += 1

    with open(dest_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    return safe_name, dest_path


def _enqueue_job(files_meta: list[dict]) -> dict:
    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
        "status": "queued",
        "total": len(files_meta),
        "done": 0,
        "success": 0,
        "failed": 0,
        "created_at": time.time(),
        "items": [
            {
                "filename": it["filename"],
                "status": "queued",
                "error": "",
                "document_id": None,
            }
            for it in files_meta
        ],
    }

    with _jobs_lock:
        _jobs[job_id] = job

    for idx, meta in enumerate(files_meta):
        _job_queue.put({"job_id": job_id, "index": idx, **meta})

    return job


def _update_job_item(job_id: str, index: int, **updates):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return
        item = job["items"][index]
        item.update(updates)


def _bump_job_counts(job_id: str, *, success: bool):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job["done"] += 1
        if success:
            job["success"] += 1
        else:
            job["failed"] += 1

        if job["done"] >= job["total"]:
            job["status"] = "done"
        else:
            job["status"] = "running"


def _worker_loop():
    while True:
        try:
            task = _job_queue.get(timeout=0.5)
        except queue.Empty:
            time.sleep(QUEUE_POLL_SLEEP_SEC)
            continue

        job_id = task["job_id"]
        idx = task["index"]
        filename = task["filename"]
        file_path = task["file_path"]

        _update_job_item(job_id, idx, status="running")

        try:
            file_size = os.path.getsize(file_path)
            file_type = classify_file(filename)

            result = process_file(file_path, filename)

            doc_id = insert_document(
                filename=filename,
                file_type=file_type,
                file_path=file_path,
                file_size=file_size,
                ocr_performed=result["ocr_performed"],
                confidence_score=result["confidence_score"],
                extracted_text=result["extracted_text"],
                ocr_details=result["ocr_details"],
                processing_time_ms=result["processing_time_ms"],
            )

            _update_job_item(job_id, idx, status="done", document_id=doc_id)
            _bump_job_counts(job_id, success=True)
        except Exception as e:
            _update_job_item(job_id, idx, status="failed", error=f"{type(e).__name__}: {e}")
            _bump_job_counts(job_id, success=False)
        finally:
            _job_queue.task_done()


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload a single file, process it (OCR if needed), and index it."""
    safe_name, dest_path = _save_upload_to_disk(file)

    try:
        file_size = os.path.getsize(dest_path)
        file_type = classify_file(safe_name)

        result = process_file(dest_path, safe_name)

        doc_id = insert_document(
            filename=safe_name,
            file_type=file_type,
            file_path=dest_path,
            file_size=file_size,
            ocr_performed=result["ocr_performed"],
            confidence_score=result["confidence_score"],
            extracted_text=result["extracted_text"],
            ocr_details=result["ocr_details"],
            processing_time_ms=result["processing_time_ms"],
        )
    except HTTPException:
        if os.path.exists(dest_path):
            os.remove(dest_path)
        raise
    except Exception as e:
        if os.path.exists(dest_path):
            os.remove(dest_path)
        raise HTTPException(status_code=500, detail=f"Upload processing failed: {type(e).__name__}: {e}")

    return {
        "id": doc_id,
        "filename": safe_name,
        "file_type": file_type,
        "file_size": file_size,
        "ocr_performed": result["ocr_performed"],
        "confidence_score": result["confidence_score"],
        "extracted_text": result["extracted_text"],
        "processing_time_ms": result["processing_time_ms"],
    }


@app.post("/api/upload_batch")
async def upload_batch(files: list[UploadFile] = File(...)):
    """Upload many files at once and process them via a background queue."""
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    saved: list[dict] = []
    for f in files:
        safe_name, dest_path = _save_upload_to_disk(f)
        saved.append({"filename": safe_name, "file_path": dest_path})

    job = _enqueue_job(saved)
    return {"job_id": job["id"], "total": job["total"], "status": job["status"]}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return job


@app.get("/api/documents")
def list_documents(
    q: str = Query("", description="Search query"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List or search documents. If q is provided, uses FTS5 full-text search."""
    if q.strip():
        docs = search_documents(q, limit=limit, offset=offset)
        total = get_document_count(q)
    else:
        docs = get_all_documents(limit=limit, offset=offset)
        total = get_document_count()

    return {"documents": docs, "total": total, "limit": limit, "offset": offset}


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: int):
    """Get a single document by ID."""
    doc = get_document_by_id(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@app.delete("/api/documents/{doc_id}")
def remove_document(doc_id: int):
    """Delete a document and its file."""
    doc = get_document_by_id(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Remove file from disk
    if os.path.exists(doc["file_path"]):
        os.remove(doc["file_path"])

    delete_document(doc_id)
    return {"detail": "Document deleted", "id": doc_id}


@app.get("/api/stats")
def get_stats():
    """Get archive statistics."""
    total = get_document_count()
    return {
        "total_documents": total,
    }
