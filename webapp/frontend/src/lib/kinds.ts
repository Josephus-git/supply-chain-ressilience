import type { LucideIcon } from 'lucide-react'
import {
  Anchor, Building2, Factory, Landmark, Package, PlaneLanding, Ship, Truck, Warehouse,
} from 'lucide-react'
import type { Mode } from './palette'

export type NodeKind =
  | 'supplier' | 'parent' | 'buyer' | 'shipment' | 'product'
  | 'exit_port' | 'entry_port' | 'carrier' | 'vessel'

/**
 * Per-kind identity, Bloom-style: every node is a plain circle with its caption
 * inside; the label colour identifies the kind (the inspector names it too).
 * Fills are soft and fairly light, so captions use dark ink, except on the
 * darker fills listed in `ink`.
 */
export const KIND_META: Record<
  NodeKind,
  { label: string; plural: string; color: string; ink: string; shape: string; icon: LucideIcon; size: number }
> = {
  buyer: { label: 'Dyson buyer', plural: 'Dyson buyers', color: '#F79767', ink: '#2a1a12', shape: 'ellipse', icon: Warehouse, size: 74 },
  shipment: { label: 'Shipment', plural: 'Shipments', color: '#8DAA7E', ink: '#17200f', shape: 'ellipse', icon: Building2, size: 56 },
  supplier: { label: 'Supplier', plural: 'Suppliers', color: '#FFC454', ink: '#2b2008', shape: 'ellipse', icon: Factory, size: 60 },
  parent: { label: 'Parent company', plural: 'Parent companies', color: '#3B5BDB', ink: '#ffffff', shape: 'ellipse', icon: Landmark, size: 60 },
  product: { label: 'Product', plural: 'Products', color: '#D5A6F0', ink: '#24142e', shape: 'ellipse', icon: Package, size: 54 },
  exit_port: { label: 'Exit port', plural: 'Exit ports', color: '#82C77E', ink: '#10220f', shape: 'ellipse', icon: Anchor, size: 54 },
  entry_port: { label: 'Entry port', plural: 'Entry ports', color: '#F9B8E8', ink: '#2e1427', shape: 'ellipse', icon: PlaneLanding, size: 54 },
  carrier: { label: 'Carrier', plural: 'Carriers', color: '#3CC4D0', ink: '#0b2427', shape: 'ellipse', icon: Truck, size: 54 },
  vessel: { label: 'Vessel', plural: 'Vessels', color: '#FFB3C1', ink: '#2e1218', shape: 'ellipse', icon: Ship, size: 54 },
}

export const KIND_ORDER: NodeKind[] = [
  'buyer', 'shipment', 'supplier', 'parent', 'product', 'exit_port', 'entry_port', 'carrier', 'vessel',
]

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function kindColor(kind: NodeKind, _mode?: Mode): string {
  return KIND_META[kind]?.color ?? '#9a9a9a'
}

export const kindInk = (kind: NodeKind) => KIND_META[kind]?.ink ?? '#1a1a1a'

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
