#!/bin/bash
HOSTNAME="{host_fqdn}"

sudo mkdir -p /etc/twingate/
if [ -z "$HOSTNAME" ]; then
  HOSTNAME=$(curl http://169.254.169.254/latest/meta-data/local-hostname)
fi
EGRESS_IP=$(curl https://checkip.amazonaws.com)
{{
echo TWINGATE_URL="https://{tg_account}.twingate.com"
echo TWINGATE_ACCESS_TOKEN="{access_token}"
echo TWINGATE_REFRESH_TOKEN="{refresh_token}"
echo TWINGATE_LOG_ANALYTICS=v1
echo TWINGATE_LABEL_HOSTNAME=$HOSTNAME
echo TWINGATE_LABEL_EGRESSIP=$EGRESS_IP
echo TWINGATE_LABEL_DEPLOYEDBY=tg-pulumi-aws-ec2
}} > /etc/twingate/connector.conf
sudo systemctl enable --now twingate-connector
