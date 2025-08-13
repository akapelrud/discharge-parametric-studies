#!/usr/bin/env python

#SBATCH --account=nn12041k
#SBATCH --job-name=inception_stepper
## #SBATCH --nodes=4
## #SBATCH --ntasks-per-node=128
#SBATCH --time=0-00:10:00
#SBATCH --output=R-%x.%A-%a.out
#SBATCH --error=R-%x.%A-%a.err

import os
import sys
import json
import re
import logging
from pathlib import Path

import subprocess

# local imports
sys.path.append(os.getcwd())  # needed for local imports from slurm scripts

from parse_report import parse_report_file

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

    # SET UP sigma2 MODULES HERE
    commands = [
            'set -o errexit',
            'set -o nounset',
            'module restore system',
            'module load HDF5/1.14.0-gompi-2023a'
            ]
    p = subprocess.Popen('; '.join(commands), shell=True, executable='/bin/bash')
    while True:
        res = p.poll()
        if res is not None:
            break

    with open('structure.json') as structure_file:
        structure = json.load(structure_file)

    job_prefix = 'run_'
    if 'output_dir_prefix' in structure:
        job_prefix = structure['output_dir_prefix']

    dim = 2
    if 'dim' in structure:
        dim = structure['dim']

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

    executable = Path("..") / \
            structure['program'].format(DIMENSIONALITY=structure['dim'])
    cmd = f"mpirun {executable} {input_file} Random.seed={task_id:d}"
    log.info(f"Running inception stepper: {cmd}")
    p = subprocess.Popen(cmd, shell=True, executable="/bin/bash")
    
    while True:
        res = p.poll()
        if res is not None:
            break
