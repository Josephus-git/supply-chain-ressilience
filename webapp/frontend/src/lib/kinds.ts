import type { LucideIcon } from 'lucide-react'
import {
  Anchor, Building2, Factory, Landmark, Package, PlaneLanding, Ship, Truck, Warehouse,
} from 'lucide-react'
import { CATEGORICAL, type Mode } from './palette'

export type NodeKind =
  | 'supplier' | 'parent' | 'buyer' | 'shipment' | 'product'
  | 'exit_port' | 'entry_port' | 'carrier' | 'vessel'

/**
 * Per-kind identity. Colour is one channel; the Cytoscape shape is the second,
 * so identity never rests on colour alone. Shipments are neutral and small.
 */
export const KIND_META: Record<
  NodeKind,
  { label: string; plural: string; slot: number | null; shape: string; icon: LucideIcon; size: number }
> = {
  supplier: { label: 'Supplier', plural: 'Suppliers', slot: 0, shape: 'round-rectangle', icon: Factory, size: 46 },
  parent: { label: 'Parent company', plural: 'Parent companies', slot: 6, shape: 'round-hexagon', icon: Landmark, size: 38 },
  buyer: { label: 'Dyson buyer', plural: 'Dyson buyers', slot: 7, shape: 'star', icon: Warehouse, size: 42 },
  product: { label: 'Product', plural: 'Products', slot: 2, shape: 'ellipse', icon: Package, size: 28 },
  exit_port: { label: 'Exit port', plural: 'Exit ports', slot: 1, shape: 'round-triangle', icon: Anchor, size: 32 },
  entry_port: { label: 'Entry port', plural: 'Entry ports', slot: 3, shape: 'round-diamond', icon: PlaneLanding, size: 32 },
  carrier: { label: 'Carrier', plural: 'Carriers', slot: 4, shape: 'round-pentagon', icon: Truck, size: 32 },
  vessel: { label: 'Vessel', plural: 'Vessels', slot: 5, shape: 'round-rectangle', icon: Ship, size: 16 },
  shipment: { label: 'Shipment', plural: 'Shipments', slot: null, shape: 'ellipse', icon: Building2, size: 14 },
}

export const KIND_ORDER: NodeKind[] = [
  'supplier', 'parent', 'buyer', 'product', 'exit_port', 'entry_port', 'carrier', 'vessel', 'shipment',
]

export function kindColor(kind: NodeKind, mode: Mode): string {
  const slot = KIND_META[kind]?.slot
  return slot == null ? (mode === 'dark' ? '#6b6a65' : '#a8a7a0') : CATEGORICAL[mode][slot]
}

export const REL_LABEL: Record<string, string> = {
  SUBSIDIARY_OF: 'subsidiary of',
  SHIPPED: 'shipped',
  CONTAINS_PRODUCT: 'product',
  DEPARTED_FROM: 'departed from',
  ARRIVED_AT: 'arrived at',
  CARRIED_BY: 'carried by',
  TRANSPORTED_ON: 'on vessel',
  CONSIGNED_TO: 'consigned to',
}
