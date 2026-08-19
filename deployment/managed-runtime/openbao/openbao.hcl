disable_mlock = true
ui            = false
api_addr      = "http://openbao:8200"

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = 1
}

storage "file" {
  path = "/openbao/file"
}
