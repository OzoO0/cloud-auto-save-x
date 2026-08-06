export type PathBrowsePath = {
  name: string
  path: string
}

export type PathBrowseItem = {
  name: string
  path: string
  is_dir: boolean
  updated_at?: any
  size?: number | null
}

export type PathBrowseResponse = {
  dir_path: string
  exists: boolean
  paths: PathBrowsePath[]
  items: PathBrowseItem[]
  scanned_at: string
}

