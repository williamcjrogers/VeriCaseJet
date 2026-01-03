terraform {
  # Remote state backend (recommended for commercial use).
  #
  # Use partial configuration via `-backend-config` so bucket/key/table can differ per environment.
  #
  # Example:
  #   terraform init -backend-config=backend.hcl
  backend "s3" {}
}


