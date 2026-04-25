import { useEffect, useState, FormEvent } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import api from '../api/client'
import TaskItem from '../components/TaskItem'

export interface TaskTime {
  start: string
  end: string | null
}

export interface Task {
  title: string
  status: string | null
  time: TaskTime | null
  line_number: number
  indent: string
  body: string | null
  children: Task[]
}

const STATUS_CYCLE: Record<string, string> = {
  todo: 'in progress',
  'in progress': 'done',
  done: 'todo',
  failed: 'todo',
  started: 'in progress',
}

function updateStatusInTree(tasks: Task[], lineNumber: number, status: string): Task[] {
  return tasks.map((t) => {
    if (t.line_number === lineNumber) return { ...t, status }
    if (t.children.length) return { ...t, children: updateStatusInTree(t.children, lineNumber, status) }
    return t
  })
}

export default function DayView() {
  const { date } = useParams<{ date: string }>()
  const [tasks, setTasks] = useState<Task[]>([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [newTitle, setNewTitle] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const navigate = useNavigate()

  useEffect(() => {
    if (date) fetchTasks()
  }, [date])

  async function fetchTasks() {
    setLoading(true)
    try {
      const { data } = await api.get(`/tasks/${date}`)
      setTasks(data.tasks)
    } finally {
      setLoading(false)
    }
  }

  async function cycleStatus(task: Task) {
    const next = STATUS_CYCLE[task.status ?? 'todo'] ?? 'todo'
    await api.patch(`/tasks/${date}/${task.line_number}`, { status: next })
    setTasks((prev) => updateStatusInTree(prev, task.line_number, next))
  }

  async function addTask(e: FormEvent) {
    e.preventDefault()
    if (!newTitle.trim()) return
    setSubmitting(true)
    try {
      await api.post(`/tasks/${date}`, { title: newTitle.trim(), status: 'todo' })
      setNewTitle('')
      setShowForm(false)
      await fetchTasks()
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="page">
      <header className="topbar">
        <button className="btn-ghost" onClick={() => navigate('/')}>
          ← Back
        </button>
        <span className="topbar-title">{date}</span>
      </header>

      <main className="main-content">
        {loading ? (
          <p className="muted">Loading…</p>
        ) : tasks.length === 0 && !showForm ? (
          <p className="muted">No tasks for this day.</p>
        ) : (
          <div className="task-list">
            {tasks.map((task) => (
              <TaskItem key={task.line_number} task={task} onStatusTap={cycleStatus} />
            ))}
          </div>
        )}

        {showForm && (
          <form className="add-task-form" onSubmit={addTask}>
            <input
              autoFocus
              type="text"
              placeholder="Task title"
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
            />
            <div className="form-actions">
              <button type="submit" disabled={submitting}>
                {submitting ? 'Adding…' : 'Add'}
              </button>
              <button
                type="button"
                className="btn-ghost"
                onClick={() => { setShowForm(false); setNewTitle('') }}
              >
                Cancel
              </button>
            </div>
          </form>
        )}
      </main>

      {!showForm && (
        <button className="fab" onClick={() => setShowForm(true)} aria-label="Add task">
          +
        </button>
      )}
    </div>
  )
}
