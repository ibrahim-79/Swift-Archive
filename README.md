# OCR Archive System

A full-featured document archive system with PaddleOCR integration, full-text search indexing, and a modern web UI.

## Features

- **Smart OCR**: Only runs OCR on images and scanned PDFs. Text-based files (TXT, DOCX, native PDFs) are extracted directly — saving hardware resources.
- **Full-Text Search**: SQLite FTS5 indexing for instant search across all extracted text and filenames.
- **Modern UI**: React + TailwindCSS dark-themed interface with drag-and-drop upload, search, pagination, and document detail view.
- **Supported Formats**: PNG, JPG, JPEG, BMP, TIFF, WebP, GIF, PDF, DOCX, TXT, CSV, MD, JSON, XML, HTML

## Architecture

```
OCR-project/
├── backend/
│   ├── main.py          # FastAPI application
│   ├── database.py      # SQLite + FTS5 indexing
│   ├── ocr_engine.py    # PaddleOCR processing engine
│   ├── requirements.txt
│   └── uploads/         # Stored files
├── frontend/
│   ├── src/
│   │   ├── App.jsx      # Main React component
│   │   ├── main.jsx     # Entry point
│   │   └── index.css    # Tailwind styles
│   ├── package.json
│   └── vite.config.js
└── README.md
```

## Quick Start

### 1. Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```
3. Run with two commands
   cd frontend
   npm run desktop

Then open http://localhost:5173

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/upload` | Upload and process a file |
| GET | `/api/documents?q=&limit=&offset=` | List/search documents |
| GET | `/api/documents/{id}` | Get document details |
| DELETE | `/api/documents/{id}` | Delete a document |
| GET | `/api/stats` | Archive statistics |

## Future Plans

- Auto-discovery scan system for batch processing
- Multi-file upload
- Folder watching / hot folder
- Language selection for OCR
- Export functionality
