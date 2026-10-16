import type { CSSProperties } from 'react'

// Team-inspired accents selected for dark surfaces. Text remains neutral; these
// colors identify teams, never price direction or statistical quality.
const colors: Record<string, string> = {
  ARI: '#c94058', ATL: '#d63c51', BAL: '#9775db', BUF: '#3979d4',
  CAR: '#22a4d8', CHI: '#e77937', CIN: '#fb7936', CLE: '#e77937',
  DAL: '#86a4c8', DEN: '#fb7936', DET: '#30a1d7', GB: '#e8bd43',
  HOU: '#e54860', IND: '#5688d6', JAX: '#30b8b0', KC: '#eb4d62',
  LA: '#e6c443', LAC: '#46b9ee', LV: '#abb5c2', MIA: '#35c1b9',
  MIN: '#a581da', NE: '#d65a6f', NO: '#cdb783', NYG: '#5385d4',
  NYJ: '#41aa88', PHI: '#46b2ad', PIT: '#e8c349', SEA: '#82c64f',
  SF: '#d9565e', TB: '#ec525a', TEN: '#64b1d7', WAS: '#d4ab50',
}
const aliases: Record<string, string> = { LAR: 'LA', OAK: 'LV', SD: 'LAC', STL: 'LA', WSH: 'WAS' }
export const teamColor = (team: string) => colors[aliases[team] ?? team] ?? '#b8c6df'
export const teamStyle = (team: string) => ({ '--team-color': teamColor(team) }) as CSSProperties
export const matchupStyle = (away: string, home: string) => ({ '--away-color': teamColor(away), '--home-color': teamColor(home) }) as CSSProperties
