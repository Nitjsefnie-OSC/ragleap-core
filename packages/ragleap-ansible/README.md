# ragleap-ansible

Ansible roles that prepare a fresh Ubuntu 22.04 server for the RagLeap Helm charts. **Version 0.1.0 is not released yet.**

## What works today

| Part | Status |
|---|---|
| `ragleap_base`: packages, deploy user with key-only login, passwordless sudo, unattended-upgrades | Tested in a throwaway Ubuntu 22.04 container, run twice, second run changes nothing |
| sshd hardening (opt-in `ragleap_base_harden_ssh`) | Effective settings checked with `sshd -T`, idempotent, bad config rolled back, all in a container. A real key login against a running sshd was not tested |
| firewall (opt-in `ragleap_base_enable_firewall`) | Rules and defaults checked in a container, idempotent, sshd port always opened. `ufw enable` and real enforcement were not tested |
| Helm, k3s, installing the charts | Not implemented yet |

## Usage

```bash
cp inventory.example.ini inventory.ini   # then list your server under [ragleap_servers]
echo 'ragleap_base_deploy_ssh_public_key: "ssh-ed25519 AAAA... you@host"' > vars.yml
ansible-playbook -i inventory.ini playbooks/bootstrap.yml -e @vars.yml
```

Pass the key through a vars file or JSON. A plain `-e name=value` splits at spaces and would cut the key short, which the role now rejects.

The playbook targets only the group `ragleap_servers`, never `localhost` by default.

## Hardening SSH (opt-in)

`ragleap_base_harden_ssh: true` turns off password logins and, by default, root logins without a key. It is off by default because a mistake can lock you out of the server.

- It needs `ragleap_base_deploy_ssh_public_key`. The role refuses to run without one.
- Keep one session open while you run it, and log in as the deploy user from a second terminal before closing the first.
- `ragleap_base_ssh_permit_root_login` defaults to `prohibit-password`. Set it to `no` only after switching `ansible_user` to the deploy user, or the next run cannot connect.
- The change is a drop-in file, `/etc/ssh/sshd_config.d/10-ragleap.conf`. The whole configuration is checked with `sshd -t` before sshd is reloaded, and if the check fails the file is removed again.

## Firewall (opt-in)

`ragleap_base_enable_firewall: true` installs ufw, denies incoming traffic by default, allows outgoing traffic, and opens the ports in `ragleap_base_firewall_allow_tcp` (for example `[80, 443]`).

- The ports sshd really listens on are always opened first, read from `sshd -T`, so the firewall cannot block your own login. Without sshd the role opens 22.
- Keep one session open while you run it, and test a new login before closing the first.
- k3s needs extra rules for its pod and service networks, which this version does not add.
- The role only adds rules. It never removes one, so a port opened earlier (for example an old ssh port) stays open until you remove it with ufw.

## Tests

```bash
bash tests/container_test.sh   # needs Docker; changes nothing on the host
```

## Known limitations

- Only Ubuntu 22.04 on x86_64 has been considered.
- A container cannot run systemd, sshd or a firewall, so those parts cannot be proven that way.
