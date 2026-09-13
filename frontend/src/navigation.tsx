// A tiny navigation context so any job card, wherever it's rendered
// (Today, Jobs, Recent, Follow-ups), can open a job's detail page without
// every intermediate page having to thread an `onOpenJob` prop through.
// This app has no router library (see App.tsx) — this is the same
// state-based navigation, just reachable from a deeper component.

import { createContext, useContext } from 'react'

export type OpenJob = (jobUniqueKey: string) => void

const NavigationContext = createContext<OpenJob | null>(null)

export const NavigationProvider = NavigationContext.Provider

/** Returns a function that navigates to a job's detail page, or `null` if
 * no `NavigationProvider` is present (e.g. a component rendered in
 * isolation in a test) — callers should hide the "Open in JobOS" action
 * rather than throwing in that case. */
export function useOpenJob(): OpenJob | null {
  return useContext(NavigationContext)
}
