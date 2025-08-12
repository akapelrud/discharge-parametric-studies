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

import subprocess

# local imports
sys.path.append(os.getcwd())  # needed for local imports from slurm scripts
from parse_report import parse_report_file


def run_plasma_code(log, task_id, dry_run=False):
    report_data = []
    if dry_run:
        log.info("DRY RUN, skipping mpirun")
        # generate some test data
        report_data.append( (1234, 1.2345, -1.2345, (3.14, 3.14), (-3.14, -3.14)) )
        log.info(f"generated test data: {report_data}")
    else:
        executable = f"../inception_stepper_program{dim:d}d"
        cmd = f"mpirun {executable} run.inputs Random.seed={task_id:d}"
        log.info(f"Running inception stepper: {cmd}")
        p = subprocess.Popen(cmd, shell=True, executable="/bin/bash")
        
        # todo: We might want to store i.e. stderr output to the log file.
        while True:
            res = p.poll()
            if res is not None:
                break

        report_data = parse_report_file('report.txt',
                                  ['+/- Voltage',
                                   'Max K(+)',
                                   'Max K(-)',
                                   'Pos. max K(+)',
                                   'Pos. max K(-)'])
        report_data = report_data[1]

    # split positive and negative potential data
    table = []
    for voltage, k_p, k_n, pos_p, pos_n in report_data:
        table.append((voltage, k_p, pos_p))
        table.append((voltage, k_n, pos_n))
    sorted_table = sorted(table, key=lambda t: t[0])

    return sorted_table


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

    with open('../study_index.json') as index_file:
        index = json.load(index_file)

    job_prefix = 'run_'
    if 'output_dir_prefix' in index:
        job_prefix = index['output_dir_prefix']

    dim = 2
    if 'dim' in index:
        dim = index['dim']

    dpattern = f'^({job_prefix}[0]*{task_id:d})$'
    dname = [f for f in os.listdir() if (os.path.isdir(f) and re.match(dpattern, f))][0]
    log.info(f'chdir: {dname}')
    os.chdir(dname)

    #sorted_table = run_plasma_code(log, task_id, dry_run=dry_run)
    #log.debug(sorted_table)

    #os.chdir('..')
    # run setup script from this directory
    #configurator.setup(f'--output {dname}')
    #configurator.schedule_runs()

