export interface Features {
  // roundUp?: boolean  (comment, ignored)
  roundUp?: boolean
  carbonCredits?: boolean
  legacyToggle?: boolean
  nested?: {
    deep: string
  }
}

export interface Appearance {
  theme?: string
}

export interface Hidden {
  a: string
}

export interface NotWatched {
  zzz: string
}
