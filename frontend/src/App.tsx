import { Navigate, Route, Routes } from 'react-router-dom'
import { CheckSquare, LayoutGrid, ListChecks, MessagesSquare, MonitorPlay } from 'lucide-react'
import { AppShell } from './components/layout/AppShell'
import { Placeholder } from './routes/Placeholder'
import { Manager } from './routes/Manager'

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Navigate to="/manager" replace />} />
        <Route
          path="/worker"
          element={<Placeholder title="My work" subtitle="Your tasks and what Shlomi needs from you." icon={CheckSquare} />}
        />
        <Route path="/manager" element={<Manager />} />
        <Route
          path="/exec"
          element={<Placeholder title="Overview" subtitle="Project health, and ask Shlomi anything." icon={LayoutGrid} />}
        />
        <Route
          path="/demo"
          element={<Placeholder title="Demo console" subtitle="Drive the whole platform live." icon={MonitorPlay} />}
        />
        <Route
          path="/board"
          element={<Placeholder title="Tasks & risks" subtitle="Everything Shlomi is tracking." icon={LayoutGrid} />}
        />
        <Route
          path="/timeline"
          element={<Placeholder title="Timeline" subtitle="The full event log, as it happened." icon={ListChecks} />}
        />
        <Route
          path="/threads"
          element={<Placeholder title="Threads" subtitle="Conversations between Shlomi and the team." icon={MessagesSquare} />}
        />
        <Route path="*" element={<Navigate to="/manager" replace />} />
      </Route>
    </Routes>
  )
}
