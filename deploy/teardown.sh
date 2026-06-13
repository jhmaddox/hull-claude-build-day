#!/usr/bin/env bash
# Tear down all AWS resources created for the Hull demo (tagged
# Project=hull-hackathon) in reserv-dev / us-west-2. Run after the event.
set -euo pipefail
export AWS_PROFILE="${AWS_PROFILE:-dev-admin}" AWS_REGION="${AWS_REGION:-us-west-2}"

echo "▸ Finding tagged instances"
IIDS=$(aws ec2 describe-instances \
  --filters Name=tag:Project,Values=hull-hackathon Name=instance-state-name,Values=running,stopped,pending \
  --query "Reservations[].Instances[].InstanceId" --output text)
if [ -n "$IIDS" ]; then
  echo "  terminating: $IIDS"
  aws ec2 terminate-instances --instance-ids $IIDS >/dev/null
  aws ec2 wait instance-terminated --instance-ids $IIDS
  echo "  terminated"
fi

echo "▸ Deleting security group hull-demo-sg"
SG=$(aws ec2 describe-security-groups --filters Name=group-name,Values=hull-demo-sg \
  --query "SecurityGroups[0].GroupId" --output text 2>/dev/null || echo None)
[ "$SG" != "None" ] && [ -n "$SG" ] && aws ec2 delete-security-group --group-id "$SG" && echo "  deleted $SG" || echo "  none"

echo "▸ Deleting key pair hull-demo"
aws ec2 delete-key-pair --key-name hull-demo >/dev/null 2>&1 && echo "  deleted" || echo "  none"
rm -f "$(dirname "$0")/../.helm_data/hull-demo.pem" 2>/dev/null || true

echo "✅ teardown complete"
