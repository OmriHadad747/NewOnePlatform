import { Hammer, type LucideIcon } from 'lucide-react'
import { PageContainer, PageHeader } from '../components/PageHeader'
import { Card, EmptyState } from '../components/ui'

// Temporary scaffold page — replaced milestone-by-milestone. Kept on-brand so
// the shell reads as a finished frame while the screens land.
export function Placeholder({
  title,
  subtitle,
  icon = Hammer,
  note,
}: {
  title: string
  subtitle?: string
  icon?: LucideIcon
  note?: string
}) {
  return (
    <PageContainer>
      <PageHeader title={title} subtitle={subtitle} />
      <Card>
        <EmptyState
          icon={icon}
          title="Taking shape"
          description={note ?? 'This screen is being built in the next milestone.'}
        />
      </Card>
    </PageContainer>
  )
}
