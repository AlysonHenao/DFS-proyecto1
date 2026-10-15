output "vm1_public_ip" {
  description = "Public IP of VM1 (leader and datanode1)."
  value       = aws_instance.vm1.public_ip
}

output "vm1_private_ip" {
  description = "Private IP of VM1."
  value       = aws_instance.vm1.private_ip
}

output "vm2_public_ip" {
  description = "Public IP of VM2 (follower, datanode2 and datanode3)."
  value       = aws_instance.vm2.public_ip
}

output "vm2_private_ip" {
  description = "Private IP of VM2."
  value       = aws_instance.vm2.private_ip
}
