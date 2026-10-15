variable "aws_region" {
  description = "AWS region for the two EC2 instances."
  type        = string
}

variable "project_name" {
  description = "Prefix used for AWS resource names."
  type        = string
  default     = "dfsha"
}

variable "instance_type" {
  description = "EC2 instance type for both VMs."
  type        = string
  default     = "t3.small"
}

variable "key_name" {
  description = "Existing EC2 key pair name."
  type        = string
}

variable "ssh_cidr" {
  description = "CIDR allowed to SSH to the instances."
  type        = string
}

variable "client_cidr" {
  description = "CIDR allowed to access the REST endpoints."
  type        = string
}
