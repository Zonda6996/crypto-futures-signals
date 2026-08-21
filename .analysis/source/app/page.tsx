import report from '@/public/reports/latest.json'
import { ResearchReport } from '@/components/research-report'

export default function Page() {
  return <ResearchReport report={report} />
}
