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
import time
import math
import shutil

# local imports
sys.path.append(os.getcwd())  # needed for local imports from slurm scripts
from parse_report import parse_report_file  # noqa: E402
from config_util import handle_combination, read_input_float_field

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
    
    # Set some inception stepper only options:
    #   +Turn off plotting for inception stepper runs. The handling of the HDF5
    #   output file might create a OOM crash on slurm if the number of K values
    #   is large.
    #   +Set Driver.max_steps=0 explicitly to quench a hard abort. The .inputs
    #   file is probably shared with the ItoKMC solver step of the study, so
    #   the DischargeInceptionStepper.mode = stationary is probably going to
    #   cause an error message and a hard abort/panic.
    cmd = f"mpirun program {input_file} Random.seed={task_id:d} Driver.max_steps=0 Driver.plot_interval=-1"
    log.info(f"cmdstr: '{cmd}'")
    p = subprocess.Popen(cmd, shell=True, executable="/bin/bash")
    while p.poll() is None:
        time.sleep(0.5)
    # propagate nonzero exit code to calling jobscript
    if p.returncode != 0:
        sys.exit(p.returncode)

    # check that the maximum voltage is at or below the max_voltage used for the
    # DischargeInceptionTagger adaptive mesh refinement class:
    report_data = parse_report_file('report.txt',
                                    ['+/- Voltage', 'Max K(+)', 'Max K(-)'])

    # take last row to get the max voltage
    calculated_max_voltage = report_data[1][-1][0]
    log.info(f'DischargeInception found max voltage: {calculated_max_voltage}')

    orig_max_voltage = read_input_float_field(input_file, 'DischargeInceptionTagger.max_voltage')
    if orig_max_voltage is None:
        raise RuntimeError(f"'{input_file}' does not contain 'DischargeInceptionTagger.max_moltage' field")

    if orig_max_voltage < calculated_max_voltage:
        log.info('renaming: report.txt -> report.txt.0')
        shutil.move('report.txt', 'report.txt.0') 

        # round up to nearest kV
        new_max_voltage = math.ceil(calculated_max_voltage / 1000) * 1000
        log.info(f'Setting DischargeInceptionTagger.max_voltage = {new_max_voltage}')

        # update input file
        handle_combination({
            "mesh_max_voltage": {
                "target": input_file,
                "uri": "DischargeInceptionTagger.max_voltage"
                }
            }, dict(mesh_max_voltage=new_max_voltage))

        log.info('Rerunning DischargeInception calculations')
        p = subprocess.Popen(cmd, shell=True, executable="/bin/bash")
        while p.poll() is None:
            time.sleep(0.5)
        sys.exit(p.returncode)

