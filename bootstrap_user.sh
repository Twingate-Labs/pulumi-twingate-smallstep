#!/bin/bash
CA_URL=https://ca.tgdemo.int

curl --insecure ${CA_URL}/roots.pem -o root.pem

CA_FINGERPRINT=`step certificate fingerprint root.pem`


# Configure `step` to connect to & trust our `step-ca`.
# Pull down the CA's root certificate so we can talk to it later with TLS
step ca bootstrap --ca-url $CA_URL --fingerprint $CA_FINGERPRINT

