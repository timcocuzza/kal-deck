import type { CSSProperties } from 'react'
import palette from './collegeTeamColors.json'

// ESPN team IDs and published brand colors, captured October 26, 2026.
// Metadata only: no FCS statistics or rankings are included in this palette.
const teams: Record<string, { color: string | null; alternateColor: string | null; abbreviation: string }> = palette
const rgb = (hex: string) => [0, 2, 4].map(i => parseInt(hex.slice(i, i + 2), 16))
const brightness = (channels: number[]) => channels[0] * .2126 + channels[1] * .7152 + channels[2] * .0722

export function collegeTeamColor(id: string) {
  const team = teams[id]
  if (!team?.color) return '#b8c6df'
  let channels = rgb(team.color)
  // Black-primary programs can use a distinctive secondary accent. Keep white
  // alternates from washing out a school's primary identity.
  if (Math.max(...channels) - Math.min(...channels) < 20 && team.alternateColor) {
    const alternate = rgb(team.alternateColor)
    if (Math.max(...alternate) - Math.min(...alternate) > 35) channels = alternate
  }
  // Like NFL accents, lift dark brand colors for the dark card surface.
  const lift = Math.max(0, (110 - brightness(channels)) / (255 - brightness(channels)))
  return '#' + channels.map(c => Math.round(c + (255 - c) * lift).toString(16).padStart(2, '0')).join('')
}

export const collegeTeamStyle = (id: string) => ({ '--team-color': collegeTeamColor(id) }) as CSSProperties
export const collegeMatchupStyle = (away: string, home: string) => ({ '--away-color': collegeTeamColor(away), '--home-color': collegeTeamColor(home) }) as CSSProperties
export const collegeAbbreviation = (id: string, fallback: string) => teams[id]?.abbreviation || fallback
