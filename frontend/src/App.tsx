import { lazy, Suspense } from 'react'
import { Navigate, Outlet, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/layout/AppShell'
import { Spinner } from './components/ui'

// Route-level code splitting: each screen ships as its own chunk so the initial
// load stays small.
const Manager = lazy(() => import('./routes/Manager').then((m) => ({ default: m.Manager })))
const Worker = lazy(() => import('./routes/Worker').then((m) => ({ default: m.Worker })))
const Exec = lazy(() => import('./routes/Exec').then((m) => ({ default: m.Exec })))
const Demo = lazy(() => import('./routes/Demo').then((m) => ({ default: m.Demo })))
const Board = lazy(() => import('./routes/Board').then((m) => ({ default: m.Board })))
const Timeline = lazy(() => import('./routes/Timeline').then((m) => ({ default: m.Timeline })))
const Threads = lazy(() => import('./routes/Threads').then((m) => ({ default: m.Threads })))

function RouteFallback() {
  return (
    <div className="flex h-[60vh] items-center justify-center">
      <Spinner className="size-6" />
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route
          element={
            <Suspense fallback={<RouteFallback />}>
              <Outlet />
            </Suspense>
          }
        >
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
      </Route>
    </Routes>
  )
}
