import { projectStats } from '../../lib/health'
import { useProjectState } from '../../lib/queries'
import { Tag } from '../ui'

export function ProjectStatusPill() {
  const { data: state } = useProjectState({ poll: true })
  const stats = projectStats(state)
  return (
    <Tag tone={stats.health.tone} dot className="py-1">
      {stats.health.label}
    </Tag>
  )
}
