#!/usr/bin/env python
"""
Author André Kapelrud
Copyright © 2025 SINTEF Energi AS
"""

import os
import sys
import json
import re
import logging
import subprocess

# local imports
sys.path.append(os.getcwd())  # needed for local imports from slurm scripts

if __name__ == '__main__':

    log = logging.getLogger(sys.argv[0])
    formatter = logging.Formatter(
            '%(asctime)s | %(levelname)s :: %(message)s')
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(formatter)
    log.addHandler(sh)
    log.setLevel(logging.INFO)

    S_ENV = 'SLURM_ARRAY_TASK_ID'
    if S_ENV not in os.environ:
        raise RuntimeError(f'${S_ENV} not found in os.environ[]. Run this'
                           ' script through sbatch --array=... !!')
    task_id = int(os.environ['SLURM_ARRAY_TASK_ID'])
    log.info(f'found task id: {task_id}')

    with open('index.json') as index_file:
        index_dict = json.load(index_file)
    job_prefix = index_dict['prefix']

    dpattern = f'^({job_prefix}[0]*{task_id:d})$'  # account for possible leading zeros
    dname = [f for f in os.listdir() if (os.path.isdir(f) and re.match(dpattern, f))][0]
    log.info(f'chdir: {dname}')
    os.chdir(dname)

    input_file = None
    for f in os.listdir():
        if os.path.isfile(f) and f.endswith('.inputs'):
            input_file = f
            break

    if not input_file:
        raise ValueError('missing *.inputs file in run directory')

    cmd = f"mpirun program {input_file} Random.seed={task_id:d}"
    log.info(f"cmdstr: '{cmd}'")
    p = subprocess.Popen(cmd, shell=True, executable="/bin/bash")

    while True:
        res = p.poll()
        if res is not None:
            break
