variable "project_id" { type = string }
variable "env" { type = string }
variable "region" {
  type    = string
  default = "europe-west1"
}
variable "bq_location" {
  type    = string
  default = "EU"
}
variable "composer_image_version" {
  type        = string
  description = "  terraform state list"
  default     = "composer-3-airflow-2.10.5"
}
variable "channels" {
  type    = string
  default = "slack,email"
}
