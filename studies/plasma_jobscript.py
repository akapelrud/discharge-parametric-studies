#!/usr/bin/env python

import os
import sys
import json
import re
import logging

from subprocess import Popen, PIPE

from pathlib import Path

# local imports
sys.path.append(os.getcwd())  # needed for local imports from slurm scripts
from parse_report import parse_report_file  # noqa: E402
from config_util import (  # noqa: E402
                         copy_files, handle_combination,
                         DEFAULT_OUTPUT_DIR_PREFIX
                         )


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

    # locate .inputs file (should be in the required_files list, and copied to the
    # current directory):
    input_file = None
    for f in os.listdir():
        if os.path.isfile(f) and f.endswith('.inputs'):
            input_file = f
            break
    if not input_file:
        raise ValueError('missing *.inputs file in run directory')
    log.info(f"input file: {input_file}")

    # get inception stepper run_directory
    with open('../inception_stepper/structure.json') as db_structure_file:
        db_structure = json.load(db_structure_file)

    # determine order of parameters (might differ from the order in this study)
    if 'space_order' not in db_structure:
        raise ValueError("missing field 'space_order' in database 'inception_stepper'")
    db_param_order = db_structure['space_order']

    # load this run's parameters (radius, pressure, etc.)
    with open('parameters.json') as param_file:
        parameters = json.load(param_file)
    if 'geometry_radius' not in parameters:
        raise RuntimeError("'geometry_radius' is missing from 'parameters.json'")

    # put the parameters in the same order as the database index needs them
    db_search_index = []
    for db_param in db_param_order:
        db_search_index.append(parameters[db_param])

    with open('../inception_stepper/index.json') as db_index_file:
        db_index = json.load(db_index_file)

    # linear search through index, which is a dictionary.
    # TODO: change the index to a better file format (sqlite3)
    index = -1
    for db_i, params in db_index['index'].items():
        if params == db_search_index:
            index = int(db_i)
            break
    if index < 0:
        raise RuntimeError(f'Unable to find db parameter_set: {db_param_order} = ' +
                           f'{db_search_index}')
    log.info(f"Found database parameters {db_param_order} = {db_search_index} "
             f"at index: {index}")

    db_run_path = Path('../inception_stepper')
    if 'prefix' in db_index:
        db_run_path /= db_index['prefix'] + str(index)
    else:
        db_run_path /= DEFAULT_OUTPUT_DIR_PREFIX + str(index)

    report_data = parse_report_file(db_run_path / 'report.txt',
                                    ['+/- Voltage',
                                     'Max K(+)',
                                     'Max K(-)',
                                     'Pos. max K(+)',
                                     'Pos. max K(-)'])
    report_data = report_data[1]
    # split positive and negative potential data
    table = []
    for voltage, k_p, k_n, pos_p, pos_n in report_data:
        if k_p != 0.0:
            table.append((voltage, k_p, pos_p))
        if k_n != 0.0:
            table.append((-voltage, k_n, pos_n))
    sorted_table = sorted(table, key=lambda t: t[0])

    log.info(sorted_table)
    enum_table = list(enumerate(sorted_table))

    output_prefix = "voltage_"

    # write voltage index
    with open('index.json', 'x') as voltage_index_file:
        json.dump(dict(
            key=["voltage", "K", "particle_position"],
            prefix=output_prefix,
            index={i: item for i, item in enum_table}
            ),
                  voltage_index_file, indent=4)

    # recreate the generic job-script symlink, so that the actual .sh jobscript work:
    os.symlink('generic_array_job_jobscript.py', 'jobscript_symlink')

    # create run directories, copy files, set voltage and particle positions, etc.
    for i, row in enum_table:
        voltage_dir = Path(f'{output_prefix}{i:d}')
        os.makedirs(voltage_dir, exist_ok=False)

        # further symlink program executable
        os.symlink(Path('../program'), voltage_dir / 'program')

        required_files = [Path(f).name for f in structure['required_files']]
        copy_files(log, required_files, voltage_dir)

        # reuse the combination writing code from the configurator / config_util, by
        # building a fake combination and parameter space:
        comb_dict = dict(
                voltage=row[0],
                sphere_dist_props=[
                    row[2],  # center position
                    0.5*parameters['geometry_radius']  # half the tip's radius
                    ],
                single_particle_position=row[2]  # center position
                )
        distribution_type = 'sphere distribution'
        pspace = {
                "voltage": {
                    "target": voltage_dir/input_file,
                    "uri": "StreamerIntegralCriterion.potential",
                    },
                "sphere_dist_props": {
                    "target": voltage_dir/'chemistry.json',
                    'uri': [
                        'plasma species',
                        '+["id"="e"]',  # find electrons in list
                        'initial particles',
                        f'+["{distribution_type}"]',
                        distribution_type,  # TODO: fix duplicity here
                        ['center', 'radius']  # NB! two parameters
                        ]
                    },
                "single_particle_position": {
                    "target": voltage_dir/'chemistry.json',
                    'uri': [
                        'plasma species',
                        '+["id"="e"]',  # find electrons in list
                        'initial particles',
                        f'+["single particle"]',
                        "single particle",  # TODO: fix duplicity here
                        'center'  # NB! two parameters
                        ]
                    }
                }
        handle_combination(pspace, comb_dict)

    cmdstr = f'sbatch --array=0-{len(enum_table)-1} ' + \
            f'--job-name="{structure["identifier"]}_voltage" ' + \
            'generic_array_job.sh'
    log.debug(f'cmd string: \'{cmdstr}\'')
    p = Popen(cmdstr, shell=True, stdout=PIPE, encoding='utf-8')

    job_id = -1
    while True:  # wait until sbatch is complete
        # try to capture the job id
        line = p.stdout.readline()
        if line:
            m = re.match('^Submitted batch job (?P<job_id>[0-9]+)', line)
            if m:
                job_id = m.groupdict()['job_id']
                with open('array_job_id', 'x') as job_id_file:
                    job_id_file.write(job_id)
                log.info(f"Submitted array job (for '{structure['identifier']}" +
                         f"_voltage' combination set). [slurm job id = {job_id}]")

        if p.poll() is not None:
            break
