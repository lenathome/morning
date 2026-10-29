export interface Features {
  legacyToggle?: boolean
  extraOption?: string
  nested?: {
    deep: string
  }
}

export interface Appearance {
  theme?: string
}

export interface Hidden {
  a: string
  foo: number
}

export interface NotWatched {
  zzz: string
  yyy: string
}
