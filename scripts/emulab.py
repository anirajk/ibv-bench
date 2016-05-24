#!/usr/bin/env python

import os
import xml.etree.ElementTree as ET
import sys
import subprocess
import time
import datetime

def ssh(server, cmd, checked=True):
    if checked:
        return subprocess.check_call('ssh %s "%s"' % (server, cmd),
                                     shell=True, stdout=sys.stdout)
    else:
        return subprocess.call('ssh %s "%s"' % (server, cmd),
                               shell=True, stdout=sys.stdout)

class BenchmarkRunner(object):

    def __init__(self, server, extra_args):
        self.extra_server_args = '--hugePages'
        self.extra_client_args = extra_args + ' --hugePages'
        self.node_type = None
        self.server = server
        self.node_names = []
        self.host_names = []
        self.start_time = None
        self.end_time = None

    def __enter__(self):
        self.populate_hosts()
        self.start_time = datetime.datetime.now()
        return self 

    def __exit__(self, type, value, traceback):
       self.killall()

    def populate_hosts(self):
        out = subprocess.check_output("ssh %s /usr/bin/geni-get manifest" % self.server,
                                      shell=True)

        root = ET.fromstring(out)
        for child in root.getchildren():
          if child.tag.endswith('node'):
            for host in child.getchildren():
              if host.tag.endswith('host'):
                self.host_names.append(host.get('name'))
                self.node_names.append('node-%d' % len(self.node_names))
              if self.node_type is None and host.tag.endswith('hardware_type'):
                self.node_type = host.get('name')

    def get_name(self):
        return (self.start_time.strftime('%Y%m%d%H%M%S') +
                '-%d-clients-%s' % (len(self.node_names) - 1, self.node_type))

    def collect_results(self):
        assert(self.end_time != None)

        log_dir = os.path.join('logs', self.get_name())
        try:
            os.makedirs(log_dir)
        except:
            pass
        try:
            latest = os.path.join('logs', 'latest')
            os.unlink(latest)
            os.symlink(self.get_name(), latest)
        except:
            pass

        legend_file_name = os.path.join(log_dir, "legend_%s.log" % self.get_name())
        with open(legend_file_name, 'w') as f:
            print >> f, 'Commit: %s' % subprocess.check_output('git log -1 --oneline', shell=True)
            print >> f, 'Run on: %s' % ' '.join(self.with_fqdn(self.host_names))
            print >> f, self.end_time.strftime('Experiment completed at %d/%m/%y %H:%M:%S')
            print >> f, 'Experiment run time: %s' % str(self.end_time - self.start_time)
        subprocess.check_call("rsync -ave ssh %s:~/ibv-bench/%s*.log %s/" %
                (self.host_names[0], self.get_name(), log_dir),
                shell=True, stdout=sys.stdout)

        try:
            out = os.path.join('logs', 'latest', 'out')
            os.symlink('%s-out.log' % self.get_name(), out)
        except:
            pass

    def with_fqdn(self, hosts):
        return ['%s.apt.emulab.net' % h for h in hosts]

    def send_code(self, server):
        subprocess.check_call("rsync -ave ssh --exclude 'logs/*' " +
                              "./ %s:~/ibv-bench/" % server,
                              shell=True, stdout=sys.stdout)

    def compile_code(self, server):
        ssh(server, '(cd ibv-bench; (make clean; make -j 8) &> ~/ibv-bench/build.log)')

    def start_servers(self):
        procs = []
        for host, node in zip(self.host_names, self.node_names):
            cmd = ('(cd ibv-bench; ./ibv-bench server %s %s > server_%s.log 2>&1)' %
                        (node, self.extra_server_args, node))
            procs.append(subprocess.Popen(['ssh', host, cmd]))
        return procs

    def killall(self):
        for host in self.host_names:
            ssh(host, 'pkill -9 ibv-bench', checked=False)

    def run(self):
        try:
            for host in self.host_names:
                print 'Sending code to %s' % host
                self.send_code(host)

            for host in self.host_names:
                print 'Compiling code on %s' % host
                self.compile_code(host)

            procs = self.start_servers()

            time.sleep(5)

            print 'Starting the client'
            ssh(self.host_names[0],
                '(cd ibv-bench; ' +
                './ibv-bench client %s %s > %s-out.log 2> %s-err.log)'
                    % (' '.join(self.node_names[1:]),
                       self.extra_client_args,
                       self.get_name(),
                       self.get_name()))
        finally:
            self.end_time = datetime.datetime.now()
            print 'Collecting results'
            self.collect_results()
            print 'Results collected'


def main():
    if not os.path.exists(os.path.join('scripts', 'emulab.py')):
        raise Exception('Run this directly from top-level of the project.')

    if len(sys.argv) < 2:
        raise Exception('Need Emulab server address.')

    server = sys.argv[1]

    extra_args = ''
    if len(sys.argv) > 3:
        extra_args = ' '.join(sys.argv[2:])

    with BenchmarkRunner(server, extra_args) as br:
        print 'Found hosts %s' % ' '.join(br.host_names)
        cmd = 'run'
        if len(sys.argv) == 3:
            cmd = sys.argv[2]

        if cmd == 'run':
            br.run()

if __name__ == '__main__': main()
