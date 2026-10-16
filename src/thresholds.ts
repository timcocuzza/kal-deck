export function thresholdHits(games: { value: number | null }[], threshold: number) {
  const values = games.flatMap(game => game.value !== null && Number.isFinite(game.value) ? [game.value] : [])
  return { hits: values.filter(value => value >= threshold).length, total: values.length }
}
