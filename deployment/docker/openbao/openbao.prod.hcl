ui            = false
api_addr      = "https://openbao:8200"

listener "tcp" {
  address           = "0.0.0.0:8200"
  tls_disable       = 0
  tls_cert_file     = "/openbao/tls/server.crt"
  tls_key_file      = "/openbao/tls/server.key"
  tls_client_ca_file = "/openbao/tls/ca.crt"
}

storage "file" {
  path = "/openbao/file"
}
