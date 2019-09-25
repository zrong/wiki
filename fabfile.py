# -*- coding: utf-8 -*-
"""
fabfile
~~~~~~~~~~~~~~~~~~~

注意： 仅支持 fabric 2.1 或更高版本

用于将本地的项目与远端项目同步
"""

import os
import sys
import shutil
import subprocess
import logging

from fabric import Connection
from invoke import task
from invoke.exceptions import Exit
from patchwork import files, transfers

logger = logging.Logger('fabric', level=logging.DEBUG)
logger.addHandler(logging.StreamHandler(sys.stdout))

SITE_WEBROOT = '/srv/www/wiki.zengrong.net'
GIT_URI = 'git@github.com:zrong/wiki.git'

basedir = os.path.abspath(os.path.split(__file__)[0])
DEPLOY_DIR = '/srv/www/wiki.zengrong.net/'


class Tmux(object):
    """Tmux helper for fabric 2"""
    def __init__(self, runner, session_name='default'):
        self.session_name = session_name
        self.run_cmd = runner.run

        self.create_session()

    def create_session(self):
        test = self.run_cmd('tmux has-session -t %s' % self.session_name, warn=True)

        if test.failed:
            self.run_cmd('tmux new-session -d -s %s' % self.session_name)

        self.run_cmd(
            'tmux set-option -t %s -g allow-rename off' % self.session_name)

    def recreate(self):
        self.kill_session()
        self.create_session()

    def kill_session(self):
        self.run_cmd('tmux kill-session -t %s' % self.session_name)

    def command(self, command, pane=0):
        self.run_cmd('tmux send-keys -t %s:%s "%s" ENTER' % (
            self.session_name, pane, command))

    def new_window(self, name):
        self.run_cmd('tmux new-window -t %s -n %s' % (self.session_name, name))

    def find_window(self, name):
        test = self.run_cmd('tmux list-windows -t %s | grep \'%s\'' % (self.session_name, name), warn=True)

        return test.ok

    def rename_window(self, new_name, old_name=None):
        if old_name is None:
            self.run_cmd('tmux rename-window %s' % new_name)
        else:
            self.run_cmd('tmux rename-window -t %s %s' % (old_name, new_name))

    def wait_for(self, signal_name):
        self.run_cmd('tmux wait-for %s' % signal_name)

    def run_singleton(self, command, orig_name, wait=True):
        run_name = "run/%s" % orig_name
        done_name = "done/%s" % orig_name

        # If the program is running we wait to be finished.
        if self.find_window(run_name):
            self.wait_for(run_name)

        # If the program is not running we create a window with done_name
        if not self.find_window(done_name):
            self.new_window(done_name)

        self.rename_window(run_name, done_name)

        # Check that we can execute the commands in the correct window
        assert self.find_window(run_name)

        rename_window_cmd = 'tmux rename-window -t %s %s' % (
            run_name, done_name)
        signal_cmd = 'tmux wait-for -S %s' % run_name

        expanded_command = '%s ; %s ; %s' % (
            command, rename_window_cmd, signal_cmd)
        self.command(expanded_command, run_name)

        if wait:
            self.wait_for(run_name)


def check_upx():
    upx = shutil.which('upx')
    if upx is None:
        logger.info('no upx in path!')
        return None
    return upx


def get_static(add_end_slash=True):
    """ 获取 static 静态文件路径
    :param add_end_alash: 对于 rsync 必须加上尾部的 / ，否则 rsync 会将 dist 作为 DEPLOY_DIR 的子文件夹同步
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
    logger.info('UPX SYNC [%s] [%s] to [%s]', bucket, source, dist)


@task
def build(c):
    """ 构建 html 静态文件
    """
    from sphinx.cmd.build import build_main
    build_main(['source', 'build', '-b', 'html'])


@task
def deployupx(c):
    """ 部署最新内容到又拍云
    """
    pdir = get_static()
    upx_sync('wiki-zengrong-net', pdir, '/')


@task
def deployrsync(c):
    """ 部署最新内容到远程服务器
    """
    if not isinstance(c, Connection):
        raise Exit('Use -H to provide a host!')
    pdir = get_static()
    transfers.rsync(c, pdir, DEPLOY_DIR, exclude=[])
    logger.warn('RSYNC [%s] to [%s]', pdir, DEPLOY_DIR)


@task
def deploytmux(c):
    """ 使用 tmux 在远程服务器拉取代码并部署
    """
    if not isinstance(c, Connection):
        raise Exit('Use -H to provide a host!')
    logger.warning('conn: %s', c)
    git_dir = '$HOME/wiki.git'
    r = c.run('test -e ' + git_dir, warn=True)
    logger.warning('r: %s', r.command)
    t = Tmux(c, 'wiki')
    if r.ok:
        cmd_list = [
            'git -C {0} reset --hard'.format(git_dir),
            'git -C {0} pull origin master'.format(git_dir),
            'cd {0}'.format(git_dir),
            'sphinx-build {0}/source/ {1}'.format(git_dir, SITE_WEBROOT),
        ]
        t.run_singleton(' && '.join(cmd_list), 'sphinx', wait=False)
    else:
        t.run_singleton('git clone --recursive {0} {1}'.format(GIT_URI, git_dir), 'git', wait=False)
