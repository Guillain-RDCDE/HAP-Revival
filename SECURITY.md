# Security Policy

## Scope

This policy covers code published in this repository (`tools/`, future daemon code, future client apps). It does **not** cover security issues in Sony's stock firmware — those are out of scope (and Sony no longer ships updates).

## Reporting a vulnerability

If you find a security issue in HAP-Revival code (e.g. a tool that leaks credentials, an API client that doesn't validate input, an app with an authentication bypass), please **do not** open a public GitHub issue.

Instead, contact the maintainer directly:

- **GitHub**: open a [private security advisory](https://github.com/Guillain-RDCDE/HAP-Revival/security/advisories/new).
- **Email**: TBD (will be added when the project is public).

Include:

1. A description of the issue.
2. Steps to reproduce.
3. The version (commit SHA) you tested against.
4. Optionally: a suggested fix.

We aim to acknowledge reports within 7 days.

## Stock-firmware issues

If you find a security issue in Sony's stock firmware (e.g. the SMBv1 Samba 3.0.37 server has a CVE that affects HAP devices on shared networks), please:

- Note it in the project's `docs/02-software-stack.md` so users can mitigate.
- Open a public issue for awareness — these are not secrets, Sony's GPL release advertises the package versions.

## Out-of-scope

- Sony's hardware vulnerabilities (we have no business reporting those).
- Issues in the upstream OpenWrt / Linux / Samba / lighttpd / Dropbear codebases — report those to the upstream projects.
