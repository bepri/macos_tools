# Ansible Collection - bepri.macos_tools

This collection contains tools I found myself needing while creating a playbook for the automatic setup of MacBooks.

For the most part, it isn't terribly hard to set up idempotent setup of MacOS devices, but the primary offender of complexity was the installation of software.

Thus, the primary star of this collection is `bepri.macos_tools.install`, which can take a path or URL to a DMG or PKG installer file and install it wherever you'd like, skipping it if an installation is already detected. More information can be found at the primary documentation for `install`.

### Planned features
At some point, I may look to add some of the following to this collection:

- Setting the hostname
- Firewall enable/disable
- Installing Rosetta if needed
