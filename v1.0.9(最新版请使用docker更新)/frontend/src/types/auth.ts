export type MeResponse = {
  id: number
  username: string
  email: string
  roles: string[]
  permissions: string[]
}

export type LoginResponse = {
  access_token: string
  token_type: string
  expires_in: number
  user: MeResponse
}
