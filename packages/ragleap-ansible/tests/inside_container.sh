#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-pip >/dev/null
python3 -m pip install -q "ansible-core>=2.16,<2.17"
cd /pkg
KEY="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA test@example"
run() {
  ansible-playbook -i tests/container-inventory.ini playbooks/bootstrap.yml \
    -e ansible_become=false -e "{\"ragleap_base_deploy_ssh_public_key\": \"$KEY\"}"
}
echo "=== run 1"
run
echo "=== run 2 (must change nothing)"
out="$(run)"
echo "$out" | tail -6
echo "$out" | grep -q 'changed=0' || { echo "NOT IDEMPOTENT: second run changed something"; exit 1; }
echo "$out" | grep -q 'failed=0' || { echo "FAILED tasks on second run"; exit 1; }
echo "=== state checks"
id ragleap
test -f /home/ragleap/.ssh/authorized_keys
grep -c "$KEY" /home/ragleap/.ssh/authorized_keys
visudo -cf /etc/sudoers.d/90-ragleap
echo "=== ssh hardening on, run twice"
cat > /tmp/ssh-vars.json <<EOF
{"ragleap_base_deploy_ssh_public_key": "$KEY", "ragleap_base_harden_ssh": true, "ragleap_base_manage_services": false}
EOF
ssh_run() {
  ansible-playbook -i tests/container-inventory.ini playbooks/bootstrap.yml \
    -e ansible_become=false -e @/tmp/ssh-vars.json
}
ssh_run >/tmp/ssh1.out 2>&1 || { tail -15 /tmp/ssh1.out; echo "SSH HARDENING RUN FAILED"; exit 1; }
out="$(ssh_run)"
echo "$out" | tail -4
echo "$out" | grep -q 'changed=0' || { echo "SSH TASKS NOT IDEMPOTENT"; exit 1; }
echo "$out" | grep -q 'failed=0' || { echo "FAILED tasks on second ssh run"; exit 1; }
# Capture first: "sshd -T | grep -q" fails under pipefail because grep -q closes the pipe early.
EFFECTIVE="$(sshd -T 2>/dev/null)"
grep -E '^(passwordauthentication|kbdinteractiveauthentication|permitrootlogin|pubkeyauthentication) ' <<< "$EFFECTIVE"
grep -q '^passwordauthentication no' <<< "$EFFECTIVE" || { echo "PASSWORD AUTH STILL ON"; exit 1; }
grep -q '^kbdinteractiveauthentication no' <<< "$EFFECTIVE" || { echo "KBD-INTERACTIVE STILL ON"; exit 1; }
grep -q -E '^permitrootlogin (without-password|prohibit-password)' <<< "$EFFECTIVE" || { echo "ROOT LOGIN SETTING WRONG"; exit 1; }
echo "=== hardening without a key must be refused"
if ansible-playbook -i tests/container-inventory.ini playbooks/bootstrap.yml \
  -e ansible_become=false -e '{"ragleap_base_harden_ssh": true}' >/tmp/nokey.out 2>&1; then
  echo "HARDENING WITHOUT A KEY WAS ACCEPTED"
  exit 1
fi
grep -q "lock yourself out" /tmp/nokey.out
echo "refused without a key"
echo "=== a config that fails sshd -t must be rolled back"
rm -f /etc/ssh/sshd_config.d/10-ragleap.conf
echo "BogusDirective yes" > /etc/ssh/sshd_config.d/99-broken.conf
if ssh_run >/tmp/broken.out 2>&1; then
  echo "BROKEN CONFIG WAS ACCEPTED"
  exit 1
fi
test ! -e /etc/ssh/sshd_config.d/10-ragleap.conf || { echo "DROP-IN WAS NOT ROLLED BACK"; exit 1; }
rm -f /etc/ssh/sshd_config.d/99-broken.conf
echo "bad config rolled back"
echo "=== firewall on, run twice"
cat > /tmp/fw-vars.json <<EOF
{"ragleap_base_deploy_ssh_public_key": "$KEY", "ragleap_base_enable_firewall": true, "ragleap_base_firewall_allow_tcp": [80, 443], "ragleap_base_manage_services": false}
EOF
fw_run() {
  ansible-playbook -i tests/container-inventory.ini playbooks/bootstrap.yml \
    -e ansible_become=false -e @/tmp/fw-vars.json
}
fw_run >/tmp/fw1.out 2>&1 || { tail -15 /tmp/fw1.out; echo "FIREWALL RUN FAILED"; exit 1; }
out="$(fw_run)"
echo "$out" | tail -4
grep -q 'changed=0' <<< "$out" || { echo "FIREWALL TASKS NOT IDEMPOTENT"; exit 1; }
grep -q 'failed=0' <<< "$out" || { echo "FAILED tasks on second firewall run"; exit 1; }
ADDED="$(ufw show added)"
echo "$ADDED"
for p in 22 80 443; do grep -q "ufw allow $p/tcp" <<< "$ADDED" || { echo "PORT $p MISSING"; exit 1; }; done
grep -q '^DEFAULT_INPUT_POLICY="DROP"' /etc/default/ufw || { echo "INPUT POLICY NOT DROP"; exit 1; }
grep -q '^DEFAULT_OUTPUT_POLICY="ACCEPT"' /etc/default/ufw || { echo "OUTPUT POLICY NOT ACCEPT"; exit 1; }
echo "ports 22, 80, 443 and both default policies are in place"
echo "=== the real sshd port must stay open"
echo "Port 2222" > /etc/ssh/sshd_config.d/20-port.conf
fw_run >/tmp/fw2.out 2>&1 || { tail -15 /tmp/fw2.out; echo "FIREWALL RUN WITH PORT 2222 FAILED"; exit 1; }
ADDED="$(ufw show added)"
grep -q "ufw allow 2222/tcp" <<< "$ADDED" || { echo "SSH PORT 2222 WAS NOT OPENED"; exit 1; }
rm -f /etc/ssh/sshd_config.d/20-port.conf
echo "ssh port 2222 opened"
echo "=== an invalid port must be refused"
if ansible-playbook -i tests/container-inventory.ini playbooks/bootstrap.yml \
  -e ansible_become=false -e '{"ragleap_base_enable_firewall": true, "ragleap_base_firewall_allow_tcp": [70000], "ragleap_base_manage_services": false}' >/tmp/badport.out 2>&1; then
  echo "INVALID PORT WAS ACCEPTED"
  exit 1
fi
grep -q "whole port numbers" /tmp/badport.out
echo "invalid port refused"
echo "=== a truncated key must be rejected"
if ansible-playbook -i tests/container-inventory.ini playbooks/bootstrap.yml \
  -e ansible_become=false -e '{"ragleap_base_deploy_ssh_public_key": "ssh-ed25519"}' >/tmp/bad.out 2>&1; then
  echo "BAD KEY WAS ACCEPTED"
  exit 1
fi
grep -q "must be a full OpenSSH" /tmp/bad.out
echo "truncated key rejected"
echo "container test passed"
