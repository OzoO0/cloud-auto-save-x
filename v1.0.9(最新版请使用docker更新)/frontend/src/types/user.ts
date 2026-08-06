export type RoleItem = {
  id: number
  name: string
  description?: string | null
}

export type UserItem = {
  id: number
  username: string
  email: string
  is_active: boolean
  roles: RoleItem[]
}

export type UserListResponse = {
  page: number
  page_size: number
  total: number
  items: UserItem[]
}

export type PermissionItem = {
  id: number
  code: string
  name: string
  description?: string | null
}

export type RoleDetail = RoleItem & {
  permissions: PermissionItem[]
}
