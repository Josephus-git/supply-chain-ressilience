/**
 * Offline world geometry for the Home map: Natural Earth 1:110m countries from
 * the `world-atlas` package, bundled at build time (no tiles, no map key).
 *
 * The map is Pacific-centred because every route runs Asia -> USA. Longitudes
 * west of CUT are shifted by +360 so the Americas sit east of Asia. Whole
 * polygons are shifted together (decided by their mean longitude) so no shape
 * is torn at the seam. Antarctica is dropped: it spans every longitude and adds
 * nothing to a trade-route map.
 */
import type { Feature, FeatureCollection, Geometry, MultiPolygon, Polygon, Position } from 'geojson'
import { feature } from 'topojson-client'
import type { GeometryCollection, Topology } from 'topojson-specification'
import world from 'world-atlas/countries-110m.json'

export const CUT = -25

/** Shift a point into the Pacific-centred frame. */
export const shiftLon = (lon: number) => (lon < CUT ? lon + 360 : lon)
export const toMap = (lon: number, lat: number): [number, number] => [shiftLon(lon), lat]

function shiftPolygon(rings: Position[][]): Position[][] {
  const outer = rings[0]
  const mean = outer.reduce((s, p) => s + p[0], 0) / outer.length
  if (mean >= CUT) {
    // Mostly east of the cut; pull any stray far-west points (e.g. Russia's
    // Chukotka at -180) across too, so the polygon stays whole.
    return rings.map((r) => r.map(([x, y]) => [x < -150 ? x + 360 : x, y]))
  }
  // Mostly west of the cut (the Americas, Greenland, Chukotka's -180 side):
  // move the western-hemisphere points; a +180 seam point stays where it is.
  return rings.map((r) => r.map(([x, y]) => [x < 0 ? x + 360 : x, y]))
}

function shiftGeometry(g: Geometry): Geometry {
  if (g.type === 'Polygon') return { ...g, coordinates: shiftPolygon((g as Polygon).coordinates) }
  if (g.type === 'MultiPolygon')
    return { ...g, coordinates: (g as MultiPolygon).coordinates.map(shiftPolygon) }
  return g
}

let cached: FeatureCollection | null = null

export function pacificWorld(): FeatureCollection {
  if (cached) return cached
  const topo = world as unknown as Topology<{ countries: GeometryCollection<{ name: string }> }>
  const fc = feature(topo, topo.objects.countries) as FeatureCollection<Geometry, { name: string }>
  cached = {
    type: 'FeatureCollection',
    features: fc.features
      .filter((f) => f.properties?.name !== 'Antarctica')
      .map((f): Feature => ({ ...f, geometry: shiftGeometry(f.geometry) })),
  }
  return cached
}
