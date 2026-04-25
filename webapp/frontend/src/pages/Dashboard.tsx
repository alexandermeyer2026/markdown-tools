import { useEffect, useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import api from '../api/client'

export default function Dashboard() {
  const [dates, setDates] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const { logout } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    fetchDates()
  }, [])

  async function fetchDates() {
    try {
      const { data } = await api.get('/files')
      setDates(data.dates)
    } finally {
      setLoading(false)
    }
  }

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    const form = new FormData()
    form.append('file', file)
    try {
      await api.post('/files/upload', form)
      await fetchDates()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      alert(msg ?? 'Upload failed')
    } finally {
      setUploading(false)
      e.target.value = ''
    }
  }

  async function handleDownload(date: string) {
    const res = await api.get(`/files/${date}/download`, { responseType: 'blob' })
    const url = URL.createObjectURL(res.data as Blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${date}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  async function handleDelete(date: string) {
    if (!confirm(`Delete ${date}?`)) return
    await api.delete(`/files/${date}`)
    setDates((prev) => prev.filter((d) => d !== date))
  }

  return (
    <div className="page">
      <header className="topbar">
        <span className="topbar-title">Journal</span>
        <div className="topbar-actions">
          <button
            className="btn-ghost"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
          >
            {uploading ? 'Uploading…' : 'Upload'}
          </button>
          <button className="btn-ghost" onClick={logout}>
            Sign out
          </button>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept=".md"
          style={{ display: 'none' }}
          onChange={handleUpload}
        />
      </header>

      <main className="main-content">
        {loading ? (
          <p className="muted">Loading…</p>
        ) : dates.length === 0 ? (
          <p className="muted">No files yet. Upload a .md file to get started.</p>
        ) : (
          <div className="date-grid">
            {dates.map((date) => (
              <div
                key={date}
                className="date-card"
                onClick={() => navigate(`/day/${date}`)}
              >
                <span className="date-label">{date}</span>
                <div
                  className="date-actions"
                  onClick={(e) => e.stopPropagation()}
                >
                  <button
                    className="btn-icon"
                    title="Download"
                    onClick={() => handleDownload(date)}
                  >
                    ↓
                  </button>
                  <button
                    className="btn-icon btn-danger"
                    title="Delete"
                    onClick={() => handleDelete(date)}
                  >
                    ✕
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
