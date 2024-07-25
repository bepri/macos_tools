#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright: (c) Imani Pelton <imani@bepri.dev>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

DOCUMENTATION = r'''
---
module: macos_pkg

short_description: Installer for MacOS PKG files

version_added: "1.0.2"

description: This module can install or uninstall PKG files with support for DMG files.

options:
    source:
        description:
            - URL or path string pointing to a PKG or DMG file to be installed
            - Note that this module will always only install the first PKG found inside of a DMG
        type: str
    force:
        description:
            - Whether or not to overwrite an existing installation
        default: False
        type: bool
    location:
        description: 
            - Optionally override the default install location of a PKG with a different path.
        type: path
    type:
        description:
            - Explicitly state the filetype of the installer
            - Only necessary in cases where the path or URL of the installer does not have a file extension
        choices: [ pkg, dmg ]
        type: str
    allow_untrusted:
        description:
            - Whether or not to allow unsigned or otherwise untrusted packages to be installed
        default: False
        type: bool
    upgrade:
        description:
            - Whether or not to upgrade an existing installation.
            - MacOS installer packages are highly unstandardized, which can lead to instances where a package installer's declared version actually differs from what the software will report as its version once installed. To cope with this, this option can be set to C(False) to avoid the confusion.
        default: True
        type: bool
    id:
        description:
            - The "com." name of the package to check for. Use this when the script returns a false positive on a program already being installed
        type: str
        notes: Use of this option requires use of O(ver) as well
    ver:
        description:
            - The version of the package to be installed. This string can be initially determined by first installing the package on a test machine, then run "pkgutil --info $PKG_ID", substituting the ID from the O(id) parameter.
        type: str
        notes: Use of this option requires use of O(id) as wel.

author:
    - Imani Pelton (@bepri)
'''

EXAMPLES = r'''
# Install directly from a PKG
- name: Install latest version of Google Chrome
  macos_pkg:
    source: "/Volumes/Remote Fileshare/ChromeInstaller.pkg"

# Install from a URL
- name: Install latest version of Google Chrome
  macos_pkg:
    source: "https://dl.google.com/dl/chrome/mac/universal/stable/gcem/GoogleChrome.pkg"

# Install from a DMG
- name: Install latest version of Google Chrome
  macos_pkg:
    source: "/Volumes/Remote Fileshare/ChromeInstaller.dmg"

# Specify the filetype for an installer with no extension
- name: Install latest version of Mysterious Software
  macos_pkg:
    source: "/Volumes/Remote Fileshare/PeculiarInstaller"
    type: dmg
    allow_unsigned: True
'''

RETURN = r'''
# These are examples of possible return values, and in general should use other names for return values.
version_installed:
    description: The version of the package installed
    returned: success
    type: str
    sample: "7.22.3rev1"
'''

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.urls import fetch_url
import xml.etree.ElementTree as et
import os
import shlex
import plistlib
import re
import sys
from pkg_resources import packaging
# This doesn't seem to want to import directly but this works just fine to pull the parse function out
parse_version = packaging.version.parse

def _validate_ext(module, path: str) -> str:
    """Check that there is an appropriate file extension on a given file and return it.

    Args:
        module (Any): The Ansible module context
        url (str): The path to validate

    Returns:
        str: _description_
    """
    # isolate extension (if any)
    if (suffix_pos := path.rfind('.')) == -1:
        module.fail_json(msg = f'Unable to determine resulting filetype of {path}.\nTry using the "type" parameter.')

    # check the extension
    suffix = path[suffix_pos:]
    if suffix not in [ '.pkg', '.dmg' ]:
        module.fail_json(msg = f'Unrecognized file extension: {suffix}.\nTry using the "type" parameter.')

    return suffix

def _run_with_output(module, cmd) -> str:
    return module.run_command(shlex.split(cmd), check_rc = True)[1]

def _is_dmg(path: str) -> bool:
    return path.endswith('.dmg')

def _is_installed(module, metadata) -> bool:
    packages = _run_with_output(module, 'pkgutil --pkgs').split('\n')

    return metadata['id'] in packages

def get_metadata(module, path: str) -> dict:
    """Return a metadata object describing the package to install

    Args:
        module (Any): Ansible module context
        path (str): Path to package

    Returns:
        dict: A dict with two self-explanatory entries: "version" and "id"
    """
    # Handle if "id" and "ver" are set from the playbook
    if module.params['id']:
        return {
            'version': module.params['ver'],
            'id': module.params['id'],
        }
    res = {}
    try:
        # Filter the package's contents with tar to get the PackageInfo file
        metadata = _run_with_output(module, f'tar xOqf "{path}" "*PackageInfo$"')
        metadata = et.fromstring(metadata)
    except:
        # Fail if we can't find the PackageInfo file
        module.fail_json(msg = f'Unable to find package properties in {path} - this usually is because the "PackageInfo" file does not exist in the PKG.')

    # Get the package version
    bundle = metadata.find('bundle').attrib
    if not (ver := bundle.get('CFBundleVersion', None)):
        module.fail_json(msg = 'Package does not specify its version number - PKG may be invalid.')

    res['version'] = re.sub(r'\s', '', ver)
    res['id'] = metadata.attrib['identifier']

    return res

def install(module, pkg_path: str, metadata: str) -> int:
    """Install a package

    Args:
        module (Any): Ansible module context
        pkg_path (str): Path to a local .pkg file
        metadata (str): Metadata object from `get_metadata()`

    Returns:
        int: Success value. 2 means the program was already installed, 1 means it was already installed but an upgrade was not necessary either, 0 is success.
    """
    if _is_installed(module, metadata):
        # Skip if the user does not want to attempt upgrades
        if module.params['upgrade'] == False:
            return 2
        
        # Test the installed version number against the one in the pkg file
        installed_ver = _run_with_output(module, f'pkgutil --pkg-info {metadata["id"]}')
        installed_ver = re.search(r'version: (.*)', installed_ver).group(1)
        if parse_version(installed_ver) >= parse_version(metadata['version']) and not module.params['force']:
            return 1
    
    # Actual install command
    result = module.run_command(
        shlex.split(
            f'installer -pkg "{pkg_path}" ' + 
            f'-target {module.params["location"] or "/"} ' +
            f'{"-allowUntrusted " if module.params["allow_untrusted"] else ""}'
        )
    )

    # Error out if the install result was nonzero, then pass stderr from the install command as an error message
    if result[0]:
        module.exit_json(msg = result[1])
    
    return 0

def main():
    module = AnsibleModule(
        argument_spec = dict(
            source = dict(type = 'str', required = True),
            location = dict(type = 'path'),
            type = dict(type = 'str', choices = [ 'pkg', 'dmg' ]),
            allow_untrusted = dict(type = 'bool', default = False),
            force = dict(type = 'bool', default = False),
            upgrade = dict(type = 'bool', default = True),
            id = dict(type = 'str'),
            ver = dict(type = 'str'),
        ),
        required_together = [
            ('id', 'ver')
        ],
        supports_check_mode = True,
    )

    source = module.params['source']
    type = module.params['type']

    result = dict(
        changed = False,
    )

    # Check if this is a URL
    url = re.match(r'^((http|https)://)[-a-zA-Z0-9@:%._\+~#?&//=]{2,256}\.[a-z]{2,6}\b([-a-zA-Z0-9@:%._\+~#?&//=]*)$', source) != None

    # Download from the URL if one is provided, then set path
    if url:
        import tempfile
        path = tempfile.mktemp()
        path += _validate_ext(module, source)

        resp, info = fetch_url(module, source)

        if info['status'] != 200:
            module.fail_json(msg = f'Unable to download from {source}: {info["msg"]}')

        with open(path, 'wb') as fout:
            fout.write(resp.read())
    else:
        path = source

    # If we're handed a DMG, mount it and find the first PKG in there
    if type == 'dmg' or _is_dmg(path):
        module.run_command(shlex.split(f'hdiutil attach "{path}"'))
        plist = module.run_command(shlex.split('hdiutil info -plist'))[1]
        plist = plistlib.loads(bytes(plist, encoding=sys.stdout.encoding))

        mount_point = None

        # Find mounting point of the DMG
        for image in plist['images']:
            if image.get('image-path') == path:
                for se in image['system-entities']:
                    if mount_point := se.get('mount-point'):
                        break
                break

        # Find PKG within the DMG mount point
        pkg_path = None
        for base, _, files in os.walk(mount_point):
            for file in files:
                if file.endswith('.pkg'):
                    pkg_path = os.path.join(base, file)
                    break
        else:
            if not pkg_path:
                module.fail_json(msg = f'Unable to locate any .pkg files in {path}')
    else:
        pkg_path = path

    metadata = get_metadata(module, pkg_path)

    install_result = install(module, pkg_path, metadata)
    if install_result == 0:
        result['changed'] = True

    if type == "dmg" or _is_dmg(path):
        module.run_command(shlex.split(f'hdiutil detach "{mount_point}"'))

    # clean up after ourselves if we downloaded an installer from a URL
    if url:
        os.remove(path)

    module.exit_json(**result, version_installed = metadata["version"])

if __name__ == '__main__':
    main()
