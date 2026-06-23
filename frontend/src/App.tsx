import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/layout/AppShell'
import { Manager } from './routes/Manager'
import { Board } from './routes/Board'
import { Timeline } from './routes/Timeline'
import { Threads } from './routes/Threads'
import { Worker } from './routes/Worker'
import { Exec } from './routes/Exec'
import { Demo } from './routes/Demo'

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Navigate to="/manager" replace />} />
        <Route path="/worker" element={<Worker />} />
        <Route path="/manager" element={<Manager />} />
        <Route path="/exec" element={<Exec />} />
        <Route path="/demo" element={<Demo />} />
        <Route path="/board" element={<Board />} />
        <Route path="/timeline" element={<Timeline />} />
        <Route path="/threads" element={<Threads />} />
        <Route path="*" element={<Navigate to="/manager" replace />} />
      </Route>
    </Routes>
  )
}
