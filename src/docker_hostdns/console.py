'''
Created on 31.03.2017

@author: Arkadiusz Dzięgiel <arkadiusz.dziegiel@glorpen.pl>
'''
import sys
import signal
import logging
import argparse
from logging.handlers import SysLogHandler
from docker_hostdns.hostdns import NamedUpdater, DockerHandler
from docker_hostdns.exceptions import StopException, ConfigException
import docker_hostdns
import os

try:
    import daemon
    _has_daemon = True
except ImportError:
    _has_daemon = False

def do_quit(*args):
    raise StopException()

class PidWriter(object):
    def __init__(self, pidpath):
        super(PidWriter, self).__init__()
        
        self.pidpath = pidpath
    
    def __enter__(self):
        if os.path.exists(self.pidpath):
            raise ConfigException("Pid file %r alread exists" % self.pidpath)
        
        with open(self.pidpath, "wt") as f:
            f.write("%d" % os.getpid())
    
    def __exit__(self, *args):
        os.unlink(self.pidpath)

def parse_commandline(argv):
    
    p = argparse.ArgumentParser(
        prog="docker-hostdns" if argv[0].endswith(".py") else os.path.basename(argv[0]),
        description=docker_hostdns.__description__
    )
    p.add_argument('--zone', default="docker", help="dns zone to update, defaults to \"docker\"")
    p.add_argument('--dns-server', default='127.0.0.1', action="store", help="address of DNS server which will be updated, defaults to 127.0.0.1")
    p.add_argument('--dns-key-secret', action="store", help="DNS Server key secret for use when updating zone, use '-' to read from stdin")
    p.add_argument('--dns-key-name', action="store", help="DNS Server key name for use when updating zone")
    p.add_argument('--name', action="store", help="name to differentiate between multiple instances inside same dns zone, defaults to current hostname")
    p.add_argument('--network', default=None, action="append", help="network to fetch container names from, defaults to docker default bridge, can be used multiple times")
    
    if _has_daemon:
        p.add_argument('--daemonize', '-d', metavar="PIDFILE", action="store", default=None, help="daemonize after start and store PID at given path")
    
    p.add_argument('--verbose', '-v', default=0, action="count", help="give more output - option is additive, and can be used up to 3 times")
    p.add_argument('--syslog', default=False, action="store_true", help="enable logging to syslog")
    p.add_argument('--clear-on-exit', default=False, action="store_true", help="clear zone on exit")
    
    conf = p.parse_args(args=argv[1:])
    conf.prog = p.prog
    return conf

def execute_with_configuration(conf):
    keyring = None
    
    if conf.dns_key_name and conf.dns_key_secret:
        secret = conf.dns_key_secret
        
        if secret == "-":
            secret = sys.stdin.readline().strip()
        
        keyring={conf.dns_key_name: secret}
    
    levels = [
        logging.ERROR,
        logging.WARNING,
        logging.INFO,
        logging.DEBUG
    ]
    
    handlers = None
    
    if conf.syslog:
        h = SysLogHandler(facility=SysLogHandler.LOG_DAEMON, address='/dev/log')
        formatter = logging.Formatter(conf.prog+' [%(name)s] %(message)s', '%b %e %H:%M:%S')
        h.setFormatter(formatter)
        handlers = [h]
    
    logging.basicConfig(level=levels[min(conf.verbose, len(levels)-1)], handlers=handlers)
    
    dns_updater = NamedUpdater(conf.zone, conf.dns_server, keyring, conf.name)
    d = DockerHandler(dns_updater)
    
    dns_updater.setup()
    d.setup(conf.network)
    
    def run():
        signal.signal(signal.SIGTERM, do_quit)
        signal.signal(signal.SIGINT, do_quit)
        logger = logging.getLogger('console')
        try:
            d.run()
        except Exception as e:
            logger.exception(e)
            raise e
        
        if conf.clear_on_exit:
            dns_updater.set_hosts({})
    
    if _has_daemon and conf.daemonize:
        pid_writer = PidWriter(os.path.realpath(conf.daemonize))
        with daemon.DaemonContext(pidfile=pid_writer):
            run()
    else:
        run()

def execute(argv = None):
    if argv is None:
        argv = sys.argv
    conf = parse_commandline(argv)
    execute_with_configuration(conf)
