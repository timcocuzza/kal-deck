export function groupDataNotices(warnings: string[]) {
  const unique = [...new Set(warnings)]
  const isEmptyRow = (warning: string) => warning.includes('excluded an unidentified row with explicitly zero rushing/receiving contributions;')
  return { emptyRows: unique.filter(isEmptyRow), other: unique.filter(warning => !isEmptyRow(warning)) }
}
