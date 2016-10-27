Monitor Memory
==============

This package creates a command-line utility that will run a command
and also run a daemon monitoring memory use as the command runs. The
daemon uses the `ps` command to check memory use, so this will only
work on `UNIX`-like systems.

I've found this functionality to be particularly useful in batch
processing jobs that run in docker containers, because the output
of `ps aux` isolates only processes running in-container. So by
recording max memory use, you can track how large of containers you
need.


Usage::
  pip install monitor_memory
  monitor_memory <some command>

All arguments after the command are forwarded to the command, as is standard
input. So, for example, to run an arbitrary bash script you can use a
here-document::
  monitor_memory bash << \EOF_
  NAME="me"
  echo ${NAME}
  EOF_
