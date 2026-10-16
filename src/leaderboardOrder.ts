export function orderedLeaderboard<T extends { team: string; rank?: number | null }>(rows: readonly T[]): T[] {
  // Use the backend's exact ranks, never re-rank rounded display values.
  const rank = (row: T) => row.rank != null && Number.isFinite(row.rank) && row.rank > 0 ? row.rank : Infinity
  return [...rows].sort((a, b) => rank(a) - rank(b) || a.team.localeCompare(b.team))
}
