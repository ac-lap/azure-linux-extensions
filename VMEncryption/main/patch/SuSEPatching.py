#!/usr/bin/python
#
# Copyright 2015 Microsoft Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Requires Python 2.4+


import os
import sys
import imp
import base64
import re
import json
import platform
import shutil
import time
import traceback
import datetime
import subprocess

from AbstractPatching import AbstractPatching
from Common import *
from CommandExecutor import *


class SuSEPatching(AbstractPatching):
    def __init__(self, logger, distro_info):
        super(SuSEPatching, self).__init__(distro_info)

        self.distro_info = distro_info
        self.command_executor = CommandExecutor(logger)

        if distro_info[1] == "11":
            self.logger = logger
            self.base64_path = '/usr/bin/base64'
            self.bash_path = '/bin/bash'
            self.blkid_path = '/sbin/blkid'
            self.cryptsetup_path = '/sbin/cryptsetup'
            self.cat_path = '/bin/cat'
            self.dd_path = '/bin/dd'
            self.e2fsck_path = '/sbin/e2fsck'
            self.echo_path = '/bin/echo'
            self.lsblk_path = '/bin/lsblk'
            self.lsscsi_path = '/usr/bin/lsscsi'
            self.mkdir_path = '/bin/mkdir'
            self.mount_path = '/bin/mount'
            self.openssl_path = '/usr/bin/openssl'
            self.resize2fs_path = '/sbin/resize2fs'
            self.umount_path = '/bin/umount'
            self.blockdev_path = '/sbin/blockdev'
        else:
            self.logger = logger
            self.base64_path = '/usr/bin/base64'
            self.bash_path = '/bin/bash'
            self.blkid_path = '/usr/bin/blkid'
            self.cat_path = '/bin/cat'
            self.cryptsetup_path = '/usr/sbin/cryptsetup'
            self.dd_path = '/usr/bin/dd'
            self.e2fsck_path = '/sbin/e2fsck'
            self.echo_path = '/usr/bin/echo'
            self.lsblk_path = '/usr/bin/lsblk'
            self.lsscsi_path = '/usr/bin/lsscsi'
            self.mkdir_path = '/usr/bin/mkdir'
            self.mount_path = '/usr/bin/mount'
            self.openssl_path = '/usr/bin/openssl'
            self.resize2fs_path = '/sbin/resize2fs'
            self.umount_path = '/usr/bin/umount'

    def install_extras(self):
        packages = ['cryptsetup', 'lsscsi']
        cmd = " ".join((['zypper', 'install', '-l', '-y'] + packages))
        self.command_executor.Execute(cmd)
        
        if not self.distro_info[1] == "11":
            packages = ['python-pip', 'gcc', 'libffi-devel', 'openssl-devel', 'python-devel']
            cmd = " ".join(['zypper', 'install', '-l', '-y'] + packages)
            self.command_executor.Execute(cmd)
        
            cmd = " ".join(['pip', 'install', 'jwt'])
            self.command_executor.Execute(cmd)
        
            cmd = " ".join(['pip', 'install', 'adal'])
            self.command_executor.Execute(cmd)

    def update_prereq(self):
        pass