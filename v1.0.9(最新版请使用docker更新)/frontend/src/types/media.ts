export type DoubanSubCategory = {
  key: string
  label: string
}

export type DoubanCategory = {
  key: string
  label: string
  media_type: 'movie' | 'tv' | string
  subs: DoubanSubCategory[]
}

export type DoubanCategoryList = {
  categories: DoubanCategory[]
}

export type TMDBBrief = {
  id?: number | null
  media_type: 'movie' | 'tv' | string
  title?: string | null
  original_title?: string | null
  release_date?: string | null
  name?: string | null
  original_name?: string | null
  first_air_date?: string | null
  overview?: string | null
  poster_path?: string | null
  vote_average?: number | null
}

export type DoubanListItem = {
  id: string
  title: string
  year?: string | null
  url?: string | null
  pic?: { normal?: string | null } | null
  rating?: { value?: number | null } | null
  card_subtitle?: string | null
  tmdb?: TMDBBrief | null
}

export type MediaDiscoverList = {
  success: boolean
  message?: string | null
  notice?: string | null
  tmdb_configured: boolean
  is_mock_data?: boolean | null
  mock_reason?: string | null
  total: number
  items: DoubanListItem[]
}

export type TMDBSearchList = {
  configured: boolean
  page: number
  total_pages: number
  total_results: number
  items: TMDBBrief[]
}

export type TMDBDetail = {
  media_type: string
  data: Record<string, any>
  update_weekdays?: number[]
  episode_weekdays?: number[]
}
