import { groupDataNotices } from './dataNotices'

export function DataNotices({ warnings, issues = [] }: {
  warnings: string[]; issues?: { market: string; reason: string }[]
}) {
  const { emptyRows, other } = groupDataNotices(warnings)
  const count = emptyRows.length + other.length + issues.length
  if (!count) return null
  return <details className="provenance">
    <summary>Data checks ({count})</summary>
    {!!emptyRows.length && <>
      <p>{emptyRows.length} empty source {emptyRows.length === 1 ? 'row was' : 'rows were'} skipped. These rows have no player identity and zero rushing or receiving contributions, so removing them does not change those totals.</p>
      <p>Deck checks the remaining player statistics against team totals. Statistics that cannot be verified appear as unavailable or incomplete beside the affected value.</p>
      <details><summary>Skipped-row details</summary><ul>{emptyRows.map(warning => <li key={warning}>{warning}</li>)}</ul></details>
    </>}
    {!!other.length && <ul>{other.map(warning => <li key={warning}>{warning}</li>)}</ul>}
    {!!issues.length && <ul>{issues.map((issue, index) => <li key={index}>{issue.market}: {issue.reason}</li>)}</ul>}
  </details>
}
