import { Task } from '../pages/DayView'

const STATUS_ICONS: Record<string, string> = {
  todo: '○',
  'in progress': '◐',
  done: '✓',
  failed: '✗',
  started: '~',
}

interface Props {
  task: Task
  onStatusTap: (task: Task) => void
  depth?: number
}

export default function TaskItem({ task, onStatusTap, depth = 0 }: Props) {
  const status = task.status ?? 'todo'
  const icon = STATUS_ICONS[status] ?? '○'
  const cssStatus = status.replace(' ', '-')

  return (
    <div className="task-item-wrapper" style={{ paddingLeft: `${depth * 16}px` }}>
      <div className={`task-item status-${cssStatus}`}>
        <button className="status-btn" onClick={() => onStatusTap(task)} aria-label={`Status: ${status}`}>
          {icon}
        </button>
        <div className="task-body">
          <span className="task-title">{task.title}</span>
          {task.time && (
            <span className="task-time">
              {task.time.start}
              {task.time.end ? `–${task.time.end}` : ''}
            </span>
          )}
          {task.body && <p className="task-notes">{task.body}</p>}
        </div>
      </div>
      {task.children.map((child) => (
        <TaskItem
          key={child.line_number}
          task={child}
          onStatusTap={onStatusTap}
          depth={depth + 1}
        />
      ))}
    </div>
  )
}
