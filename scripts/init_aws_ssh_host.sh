#!/bin/bash
#
# This script will get an SSH host certificate from our CA and add a weekly
# cron job to rotate the host certificate. It should be run as root.
#
# See https://smallstep.com/blog/diy-single-sign-on-for-ssh/ for full instructions

CA_URL="{ca_url}"
HOSTNAME="{host_fqdn}"

STEPCLI_VERSION="0.24.4"
TIMEOUT=300
EXPECTEDCODE=200

curl -LO https://github.com/smallstep/cli/releases/download/v${{STEPCLI_VERSION}}/step-cli_${{STEPCLI_VERSION}}_amd64.deb
dpkg -i step-cli_${{STEPCLI_VERSION}}_amd64.deb


echoerr()
{{
  if [[ $QUIET -ne 1 ]]; then echo "$@" 1>&2; fi
}}


wait_for_ca()
{{
    URI="$CA_URL/health"
    if [[ $TIMEOUT -gt 0 ]]; then
        echoerr "Waiting $TIMEOUT seconds for $URI to get a $EXPECTEDCODE HTTP code"
    else
        echoerr "Waiting for $URI without a timeout"
    fi
    WAIT_START_TS=$(date +%s)
    while :
    do
            STATUS_CODE=$(curl --connect-timeout 2 --insecure -s -o /dev/null -w ''%{{http_code}}'' $URI)
            test "$STATUS_CODE" == "$EXPECTEDCODE"
            OUTCOME=$?
        if [[ $OUTCOME -eq 0 ]]; then
            WAIT_END_TS=$(date +%s)
            echoerr "$URI is alive after $((WAIT_END_TS - WAIT_START_TS)) seconds"
            break
        fi
        sleep 1
    done
    return $OUTCOME
}}

wait_for_ca
OUTCOME=$?
if [[ $OUTCOME -ne 0 ]]; then
    echoerr "Could not contact CA - will not provision SSH certificate"
    exit $OUTCOME
fi


# Obtain your CA fingerprint by running this on your CA:
#   # step certificate fingerprint $(step path)/certs/root_ca.crt
curl --insecure https://{CA_URL}/roots.pem -o root.pem

CA_FINGERPRINT=`step certificate fingerprint root.pem`


# Configure `step` to connect to & trust our `step-ca`.
# Pull down the CA's root certificate so we can talk to it later with TLS
step ca bootstrap --ca-url $CA_URL --fingerprint $CA_FINGERPRINT

# Install the CA cert for validating user certificates (from /etc/step-ca/certs/ssh_user_key.pub` on the CA).
step ssh config --roots > $(step path)/certs/ssh_user_key.pub

# Get an SSH host certificate - NOTE: If there's no public hostname this script will FAIL
if [ -z "$HOSTNAME" ]; then
    HOSTNAME="$(curl -s http://169.254.169.254/latest/meta-data/public-hostname)"
fi
LOCAL_HOSTNAME="$(curl -s http://169.254.169.254/latest/meta-data/local-hostname)"

# This helps us avoid a potential race condition / clock skew issue
# "x509: certificate has expired or is not yet valid: current time 2020-04-01T17:52:51Z is before 2020-04-01T17:52:52Z"
sleep 1

# The TOKEN is a JWT with the instance identity document and signature embedded in it.
TOKEN=$(step ca token $HOSTNAME --ssh --host --provisioner "Amazon Web Services")

# To inspect $TOKEN, run
# $ echo $TOKEN | step crypto jwt inspect --insecure
#
# To inspect the Instance Identity Document embedded in the token, run
# $ echo $TOKEN | step crypto jwt inspect --insecure | jq -r ".payload.amazon.document" | base64 -d

# Ask the CA to exchange our instance token for an SSH host certificate
step ssh certificate $HOSTNAME /etc/ssh/ssh_host_ecdsa_key.pub \
    --host --sign --provisioner "Amazon Web Services" \
    --principal $HOSTNAME --principal $LOCAL_HOSTNAME \
    --token $TOKEN

# Configure and restart `sshd`
tee -a /etc/ssh/sshd_config > /dev/null <<EOF
# SSH CA Configuration

# This is the CA's public key, for authenticatin user certificates:
TrustedUserCAKeys $(step path)/certs/ssh_user_key.pub

# This is our host private key and certificate:
HostKey /etc/ssh/ssh_host_ecdsa_key
HostCertificate /etc/ssh/ssh_host_ecdsa_key-cert.pub
EOF

service ssh restart

# Now add a weekly cron script to rotate our host certificate.
cat <<EOF > /etc/cron.weekly/rotate-ssh-certificate
#!/bin/sh

export STEPPATH=/root/.step

cd /etc/ssh && step ssh renew ssh_host_ecdsa_key-cert.pub ssh_host_ecdsa_key --force 2> /dev/null

exit 0
EOF

chmod 755 /etc/cron.weekly/rotate-ssh-certificate