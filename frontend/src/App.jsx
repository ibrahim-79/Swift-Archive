import React, { useState, useEffect, useCallback } from 'react'
import axios from 'axios'

const API = '/api'

const fileTypeLabel = (type) => {
  if (!type) return 'unknown'
  return String(type).toUpperCase()
}

const formatBytes = (bytes) => {
  if (!bytes) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

const formatDate = (iso) => {
  if (!iso) return ''
  const d = new Date(iso + 'Z')
  return d.toLocaleString()
}

const confidenceText = (score, ocrPerformed) => {
  if (!ocrPerformed) return 'N/A'
  const s = Number(score)
  if (!Number.isFinite(s)) return '0%'
  return `${(s * 100).toFixed(1)}%`
}

export default function App() {
  const [documents, setDocuments] = useState([])
  const [total, setTotal] = useState(0)
  const [query, setQuery] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [page, setPage] = useState(0)
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadResult, setUploadResult] = useState(null)
  const [selectedDoc, setSelectedDoc] = useState(null)
  const [stats, setStats] = useState({ total_documents: 0 })
  const [batchJobId, setBatchJobId] = useState('')
  const [batchJob, setBatchJob] = useState(null)

  const LIMIT = 20

  const fetchDocuments = useCallback(async () => {
    setLoading(true)
    try {
      const res = await axios.get(`${API}/documents`, {
        params: { q: query, limit: LIMIT, offset: page * LIMIT }
      })
      setDocuments(res.data.documents)
      setTotal(res.data.total)
    } catch (err) {
      console.error('Failed to fetch documents:', err)
    }
    setLoading(false)
  }, [query, page])

  const fetchStats = async () => {
    try {
      const res = await axios.get(`${API}/stats`)
      setStats(res.data)
    } catch (err) {
      console.error(err)
    }
  }

  useEffect(() => {
    fetchDocuments()
  }, [fetchDocuments])

  useEffect(() => {
    fetchStats()
  }, [])

  useEffect(() => {
    if (!batchJobId) return

    let cancelled = false
    const interval = setInterval(async () => {
      try {
        const res = await axios.get(`${API}/jobs/${batchJobId}`)
        if (cancelled) return
        setBatchJob(res.data)

        if (res.data.status === 'done') {
          clearInterval(interval)
          setBatchJobId('')
          fetchDocuments()
          fetchStats()
        }
      } catch (err) {
        const status = err?.response?.status
        if (status === 404) {
          clearInterval(interval)
          if (cancelled) return
          setBatchJobId('')
          setBatchJob(null)
          setUploadResult({ success: false, error: 'Queue job not found (backend restarted). Please re-upload the batch.' })
          return
        }
        console.error(err)
      }
    }, 800)

    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [batchJobId, fetchDocuments])

  const handleSearch = (e) => {
    e.preventDefault()
    setPage(0)
    setQuery(searchInput)
  }

  const handleUpload = async (file) => {
    if (!file) return
    setUploading(true)
    setUploadResult(null)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const res = await axios.post(`${API}/upload`, formData)
      setUploadResult({ success: true, data: res.data })
      fetchDocuments()
      fetchStats()
    } catch (err) {
      setUploadResult({ success: false, error: err.response?.data?.detail || err.message })
    }
    setUploading(false)
  }

  const handleBatchUpload = async (files) => {
    const list = Array.from(files || [])
    if (list.length === 0) return

    setUploading(true)
    setUploadResult(null)
    setBatchJob(null)
    try {
      const formData = new FormData()
      for (const f of list) formData.append('files', f)

      const res = await axios.post(`${API}/upload_batch`, formData)
      setBatchJobId(res.data.job_id)
      setUploadResult({
        success: true,
        data: {
          filename: `${res.data.total} files queued`,
          file_type: 'batch',
          ocr_performed: false,
          confidence_score: 0,
          processing_time_ms: 0
        }
      })
    } catch (err) {
      setUploadResult({ success: false, error: err.response?.data?.detail || err.message })
    }
    setUploading(false)
  }

  const handleFileInput = (e) => {
    handleUpload(e.target.files[0])
    e.target.value = ''
  }

  const handleMultiFileInput = (e) => {
    handleBatchUpload(e.target.files)
    e.target.value = ''
  }

  const handleDrop = (e) => {
    e.preventDefault()
    const file = e.dataTransfer.files[0]
    if (file) handleUpload(file)
  }

  const handleDelete = async (id) => {
    if (!confirm('Delete this document from the archive?')) return
    try {
      await axios.delete(`${API}/documents/${id}`)
      if (selectedDoc?.id === id) setSelectedDoc(null)
      fetchDocuments()
      fetchStats()
    } catch (err) {
      console.error(err)
    }
  }

  const totalPages = Math.ceil(total / LIMIT)

  return (
    <div style={{ padding: 12, fontFamily: 'Tahoma, Arial, sans-serif', fontSize: 13, background: '#fff', color: '#000', minHeight: '100vh' }}>
      <div style={{ border: '1px solid #999', padding: 10, marginBottom: 12, background: '#eee', color: '#000' }}>
        <h1 style={{ margin: 0, fontSize: 18 }}>OCR Archive</h1>
        <div style={{ marginTop: 6 }}>Total documents: <b>{stats.total_documents}</b></div>
      </div>

      <div
        style={{ border: '1px dashed #666', padding: 12, marginBottom: 12, background: '#fafafa', color: '#000' }}
        onDragOver={(e) => { e.preventDefault() }}
        onDrop={handleDrop}
      >
        <div style={{ marginBottom: 8 }}>
          <b>Upload file</b>
        </div>
        <input type="file" onChange={handleFileInput} disabled={uploading} />
        <div style={{ marginTop: 8, color: '#333' }}>
          {uploading ? 'Processing... (OCR can take time)' : 'Tip: you can also drag and drop a file onto this box.'}
        </div>
      </div>

      <div style={{ border: '1px dashed #666', padding: 12, marginBottom: 12, background: '#fafafa', color: '#000' }}>
        <div style={{ marginBottom: 8 }}>
          <b>Upload many images / folder</b>
        </div>
        <div style={{ marginBottom: 6 }}>
          <input type="file" multiple onChange={handleMultiFileInput} disabled={uploading || !!batchJobId} />
        </div>
        <div style={{ marginBottom: 6 }}>
          <input type="file" multiple webkitdirectory="" directory="" onChange={handleMultiFileInput} disabled={uploading || !!batchJobId} />
        </div>
        <div style={{ color: '#333' }}>
          This uses a queue (low load). If folder picker doesn't work, use the multi-file picker.
        </div>
      </div>

      {(batchJobId || batchJob) && (
        <div style={{ border: '1px solid #999', padding: 10, marginBottom: 12, background: '#fff', color: '#000' }}>
          <div><b>Queue status</b></div>
          <div>Job ID: {batchJobId || batchJob?.id}</div>
          <div>
            Status: <b>{batchJob?.status || 'queued'}</b> | Done: <b>{batchJob?.done ?? 0}</b> / <b>{batchJob?.total ?? '?'}</b> | Success: <b>{batchJob?.success ?? 0}</b> | Failed: <b>{batchJob?.failed ?? 0}</b>
          </div>
          {batchJob?.failed > 0 && (
            <div style={{ marginTop: 6 }}>
              <b>Failed items:</b>
              <ul style={{ marginTop: 4 }}>
                {batchJob.items.filter(i => i.status === 'failed').slice(0, 5).map((i, idx) => (
                  <li key={idx}>{i.filename}: {i.error}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {uploadResult && (
        <div
          style={{
            border: '1px solid #999',
            padding: 10,
            marginBottom: 12,
            background: uploadResult.success ? '#eaffea' : '#ffecec',
            color: '#000'
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
            <div style={{ flex: 1 }}>
              {uploadResult.success ? (
                <div>
                  <div><b>Uploaded:</b> {uploadResult.data.filename}</div>
                  <div>
                    <b>Type:</b> {uploadResult.data.file_type} | <b>OCR:</b> {uploadResult.data.ocr_performed ? 'Yes' : 'No'} | <b>Confidence:</b> {confidenceText(uploadResult.data.confidence_score, uploadResult.data.ocr_performed)} | <b>Time:</b> {uploadResult.data.processing_time_ms}ms
                  </div>
                </div>
              ) : (
                <div><b>Error:</b> {uploadResult.error}</div>
              )}
            </div>
            <button onClick={() => setUploadResult(null)} type="button">X</button>
          </div>
        </div>
      )}

      <form onSubmit={handleSearch} style={{ border: '1px solid #999', padding: 10, marginBottom: 12, background: '#f7f7f7', color: '#000' }}>
        <div style={{ marginBottom: 6 }}><b>Search</b></div>
        <input
          type="text"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          placeholder="Search extracted text or filenames"
          style={{ width: 420, maxWidth: '100%', background: '#fff', color: '#000', border: '1px solid #999' }}
        />
        <button type="submit" style={{ marginLeft: 8 }}>Search</button>
        {query && (
          <button
            type="button"
            style={{ marginLeft: 8 }}
            onClick={() => { setSearchInput(''); setQuery(''); setPage(0) }}
          >
            Clear
          </button>
        )}
        {query && (
          <div style={{ marginTop: 8 }}>
            Showing results for: <b>{query}</b> (total: <b>{total}</b>)
          </div>
        )}
      </form>

      <div style={{ border: '1px solid #999', padding: 10, background: '#fff', color: '#000' }}>
        <div style={{ marginBottom: 8 }}><b>Documents</b></div>
        <div style={{ overflowX: 'auto' }}>
          <table cellPadding="4" cellSpacing="0" border="1" style={{ borderCollapse: 'collapse', width: '100%' }}>
            <thead style={{ background: '#eee', color: '#000' }}>
              <tr>
                <th align="left">ID</th>
                <th align="left">Filename</th>
                <th align="left">Type</th>
                <th align="left">Size</th>
                <th align="left">OCR</th>
                <th align="left">Confidence</th>
                <th align="left">Uploaded</th>
                <th align="left">Text (preview)</th>
                <th align="left">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={9}>Loading...</td>
                </tr>
              ) : documents.length === 0 ? (
                <tr>
                  <td colSpan={9}>{query ? 'No matches.' : 'No documents yet.'}</td>
                </tr>
              ) : (
                documents.map((doc) => (
                  <tr key={doc.id}>
                    <td>{doc.id}</td>
                    <td title={doc.filename}>{doc.filename}</td>
                    <td>{fileTypeLabel(doc.file_type)}</td>
                    <td>{formatBytes(doc.file_size)}</td>
                    <td>{doc.ocr_performed ? 'Yes' : 'No'}</td>
                    <td>{confidenceText(doc.confidence_score, doc.ocr_performed)}</td>
                    <td>{formatDate(doc.uploaded_at)}</td>
                    <td
                      style={{ maxWidth: 420, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', cursor: 'pointer' }}
                      title="Click to view full text"
                      onClick={() => setSelectedDoc(doc)}
                      dangerouslySetInnerHTML={{
                        __html: doc.highlighted_text
                          ? doc.highlighted_text.substring(0, 140) + '...'
                          : (doc.extracted_text || '').substring(0, 140) + (doc.extracted_text?.length > 140 ? '...' : '')
                      }}
                    />
                    <td>
                      <button type="button" onClick={() => setSelectedDoc(doc)}>View</button>
                      <button type="button" onClick={() => handleDelete(doc.id)} style={{ marginLeft: 6 }}>Delete</button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {totalPages > 1 && (
          <div style={{ marginTop: 10 }}>
            <button type="button" onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0}>Prev</button>
            <span style={{ margin: '0 10px' }}>Page {page + 1} / {totalPages}</span>
            <button type="button" onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={page >= totalPages - 1}>Next</button>
          </div>
        )}
      </div>

      {selectedDoc && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: 'rgba(0,0,0,0.4)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 12
          }}
          onClick={() => setSelectedDoc(null)}
        >
          <div
            style={{ background: '#fff', color: '#000', border: '1px solid #333', padding: 12, width: 800, maxWidth: '100%', maxHeight: '85vh', overflow: 'auto' }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: 10 }}>
              <div style={{ fontWeight: 'bold' }}>{selectedDoc.filename}</div>
              <button type="button" onClick={() => setSelectedDoc(null)}>Close</button>
            </div>

            <div style={{ marginBottom: 10 }}>
              <div><b>Type:</b> {fileTypeLabel(selectedDoc.file_type)}</div>
              <div><b>Size:</b> {formatBytes(selectedDoc.file_size)}</div>
              <div><b>OCR:</b> {selectedDoc.ocr_performed ? 'Yes' : 'No'}</div>
              <div><b>Confidence:</b> {confidenceText(selectedDoc.confidence_score, selectedDoc.ocr_performed)}</div>
              <div><b>Uploaded:</b> {formatDate(selectedDoc.uploaded_at)}</div>
              <div><b>Processing time:</b> {selectedDoc.processing_time_ms} ms</div>
            </div>

            {selectedDoc.file_type === 'image' && (
              <div style={{ marginBottom: 10 }}>
                <div><b>Preview</b></div>
                <img
                  src={`/uploads/${selectedDoc.filename}`}
                  alt={selectedDoc.filename}
                  style={{ maxWidth: '100%', maxHeight: 300, border: '1px solid #999' }}
                />
              </div>
            )}

            <div>
              <div><b>Extracted Text</b></div>
              <textarea
                readOnly
                value={selectedDoc.extracted_text || ''}
                style={{ width: '100%', height: 240, fontFamily: 'Courier New, monospace', fontSize: 12, background: '#fff', color: '#000', border: '1px solid #999' }}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
