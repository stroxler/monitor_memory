#!/usr/bin/env python
from __future__ import print_function, division
USAGE = """
Run a command and monitor memory on linux or osx

USAGE: ./run_and_monitor_memory.py COMMAND [ARGS] [<< HEREDOC]

This script will fork into two processes.
 - The child process will replace itself with a call to COMMAND, with arguments
   ARGS
 - The parent process spins off two threads, one that records the total RSS
   usage from running `ps aux` every second, and one that waits for the
   child process and any of *it's* children to finish

Once all the child processes are finished, we print the maximum total RSS
to the stderr and exit with the same status as the original child process.

We don't make any use of stdin or stdout in this script, which means you
can redirect either of them and the child process should have access. For
example, the most general use of this script is with a bash here-document, e.g.
```
  ./run_and_monitor_memory.py bash << EOF
  echo "hi from bash"
  python -c "import time; l = [1.5 * i for i in range(1000); time.sleep(5)"
  echo "bye from bash"
  EOF
```


Notes:
 - We only use standard library modules from python 2.7, so this should work
   out-of-the-box. It is untested but probably works on python 3.x
 - The original intent of this script was to be used with `docker run` in
   order to track docker resource usage - which is accruately reported
   by `ps aux` but not by `/proc/meminfo` or `top` - from inside of a
   container. But other use cases should be fine.
 - My use of fork + pipe is based on this StackOverflow post:
   http://stackoverflow.com/questions/22514121/how-can-i-wait-for-child-processes

"""
import os
import sys
import time
import threading
import subprocess


def print_stderr(content):
    sys.stderr.write(content)
    sys.stderr.write('\n')


def fork_with_pipe(executable=None, args=None):
    """
    Call os.fork() and then os.execvp() to create a child process, after
    making a pipe whose write end is open in the child and whose read end
    will be returned.

    The open pipe makes it possible for us to block until not only `pid`
    but also all its children complete - see `wait_for_child` and the
    stackoverflow reference for more details.
    """
    executable, args = _executable_and_args(executable, args)
    pipe_r, pipe_w = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.execvp(executable, args)
        raise RuntimeError('Failed to call os.execvp')
    os.close(pipe_w)
    return pid, pipe_r


def _executable_and_args(executable=None, args=None):
    if args is None:
        if executable is not None:
            args = [executable]
        else:
            args = sys.argv[1:]
            executable = sys.argv[1]
    else:
        if executable is None:
            raise ValueError('executable must be non-None if args given')
        args = [executable] + list(args)
    return executable, tuple(args)


def wait_for_child(pid, pipe_r):
    """
    Block until child process with `pid` and all of its children have exited.
    Return the exit status of `pid` (if one of its children raised an error
    put `pid` itself did not, then we have no easy way of finding out).
    
    The mechanism for knowing when all children executed is a pipe,
    which is never written to: POSIX guarantees that if the pipe is never
    written to, a call to `read(pipe_r, 1)` blocks until all processes
    which have an open file descriptor for the write end of that pipe have
    exited.
    """
    _, exit_status_indicator = os.waitpid(pid, 0)
    exit_status = exit_status_indicator // (2 ** 8)
    os.read(pipe_r, 1)
    os.close(pipe_r)
    return exit_status


def all_ps_memory_usage():
    """
    Return the total RSS (actual memory consumed) usage in megabytes, based on
    summing the RSS for every process in `ps aux` output.

    NOTE: the motivation for using `ps aux` rather than some other method of
    querying for resource consumption is that it appears to give a correct
    answer when run inside of a docker container - see the notes on the
    original purpose of this script
    """
    # NOTE:
    # on both osx and linux, the first 6 columns of ps output are
    #    USER PID %CPU %MEM VSZ RSS
    # and the units of RSS are kilobytes
    RSS_COL = 5
    KB_TO_MB = 1. / 1024
    out = subprocess.check_output(['ps', 'aux'])
    process_lines = [l for l in out.split('\n')[1:] if l != '']
    total_rss = 0
    for line in process_lines:
        proc_rss = float(line.split()[RSS_COL]) * KB_TO_MB
        total_rss += proc_rss
    return total_rss


# Globals shared between MemoryMonitoringThread and main
max_child_memory_use = 0
memory_use_lock = threading.Lock()
MEMORY_USAGE_POLL_INTERVAL = 1


class MemoryMonitoringThread(threading.Thread):

    def __init__(self):
        """
        Create a daemon thread that checks every MEMORY_USAGE_POLL_INTERVAL
        seconds for how much RSS memory is consumed according to `ps aux`,
        and records it in the global variable `max_child_memory_use`.

        """
        super(MemoryMonitoringThread, self).__init__()
        self.daemon = True

    def run(self):
        global max_child_memory_use
        while True:
            with memory_use_lock:
                max_child_memory_use = max(
                    max_child_memory_use,
                    all_ps_memory_usage()
                )
            time.sleep(MEMORY_USAGE_POLL_INTERVAL)


def main():
    if len(sys.argv) < 2:
        print_stderr(USAGE)
        sys.exit(1)
    pid, pipe_r = fork_with_pipe()
    monitor_memory = MemoryMonitoringThread()
    monitor_memory.start()
    exit_status = wait_for_child(pid, pipe_r)
    with memory_use_lock:
        print_stderr('----------------------')
        print_stderr('Max memory use: %.3fMb' % max_child_memory_use)
        print_stderr('----------------------')
    if exit_status != 0:
        print_stderr('Child exited with status: %r' % exit_status)
        sys.exit(exit_status)


if __name__ == '__main__':
    main()

