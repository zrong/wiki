# -*- coding: utf-8 -*-
"""
fabfile
~~~~~~~~~~~~~~~~~~~

注意： 仅支持 fabric 2.1 或更高版本

用于将本地的项目与远端项目同步
"""

import os
import shutil
import subprocess
import logging

from fabric import Connection
from invoke import task
from invoke.exceptions import Exit
from patchwork import files, transfers

basedir = os.path.abspath(os.path.split(__file__)[0])
log = logging.getLogger('fabric')
host = 'zengrong.net'
deploy_dir = '/srv/www/wiki.zengrong.net/'


def check_upx():
    upx = shutil.which('upx')
    if upx is None:
        log.info('no upx in path!')
        return None
    return upx


def get_static(add_end_slash=True):
    """ 获取 static 静态文件路径
    :param add_end_alash: 对于 rsync 必须加上尾部的 / ，否则 rsync 会将 dist 作为 deploy_dir 的子文件夹同步
    """
    # 因为 windows 下面的 rsync 不支持 windows 风格的绝对路径，转换成相对路径
    pdir = os.path.join(basedir, 'dist')
    # 因为 windows 下面的 rsync 不支持 windows 风格的绝对路径，转换成相对路径
    # pdir = os.path.relpath(pdir, start=pdir)
    pdir = os.path.join(basedir, 'build/html/')
    if add_end_slash and not pdir.endswith('/'):
      return pdir + '/'
    return pdir


def upx_sync(bucket, source, dist):
    upx = check_upx()
    if upx is None:
        return
    cp = subprocess.run([upx, 'info'], stdout=subprocess.PIPE, check=True)
    output = cp.stdout.decode()
    output = [line.strip() for line in output.split('\n')]
    bucket_info = {}
    for line in output:
        kv = line.split(':')
        if len(kv) > 1:
            kv = [item.strip() for item in kv]
            bucket_info[kv[0]] = kv[1]
    service_name = bucket_info.get('ServiceName')
    current_dir = bucket_info.get('CurrentDir')
    if not service_name or not current_dir or service_name != bucket:
        raise Exit('please login or switch bucket [%s]!' % bucket)
    if current_dir != '/':
        cp = subprocess.run([upx, 'cd', '/'], check=True)
    subprocess.run([upx, 'sync', source, dist])
    log.info('UPX SYNC [%s] [%s] to [%s]', bucket, source, dist)


@task
def build(c):
    """ 构建 html 静态文件
    """
    from sphinx.cmd.build import build_main
    build_main(['source', 'build', '-b', 'html'])


@task
def deployupx(c):
    """ 部署最新程序到远程服务器
    """
    pdir = get_static()
    upx_sync('wiki-zengrong-net', pdir, '/')


def getconn():
    return Connection(host, 'app')


@task
def deployrsync(c):
    """ 部署最新程序到远程服务器
    """
    pdir = get_static()
    conn = getconn()
    transfers.rsync(conn, pdir, deploy_dir, exclude=[])
    log.warn('RSYNC [%s] to [%s]', pdir, deploy_dir)
