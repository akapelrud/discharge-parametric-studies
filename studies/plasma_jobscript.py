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
import itertools
import shutil

from subprocess import Popen, PIPE

from pathlib import Path

# local imports
sys.path.append(os.getcwd())  # needed for local imports from slurm scripts
from parse_report import parse_report_file  # noqa: E402
from config_util import (  # noqa: E402
                         copy_files, backup_file,
                         get_slurm_array_task_id,
                         handle_combination,
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

    task_id = get_slurm_array_task_id()
    log.info(f'found task id: {task_id}')

    with open('structure.json') as structure_file:
        structure = json.load(structure_file)

    job_prefix = 'run_'
    if 'output_dir_prefix' in structure:
        job_prefix = structure['output_dir_prefix']

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
    
    polarity = 0  # 1,0 or -1
    if 'plasma_polarity' not in parameters:
        log.warning("'plasma_polarity' was not found in parameters.json, running for both polarities")
    else:
        if parameters['plasma_polarity'] == 'positive':
            polarity = 1
        elif parameters['plasma_polarity'] == 'negative':
            polarity = -1
    log.info(f'Running with polarity {polarity} (0:both, 1:positive, -1:negative)')

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

    Kmin = 0
    if 'K_min' not in parameters:
        log.warning("'K_min' not found in parameters, using Kmin=0")
    else:
        Kmin = parameters['K_min']

    if 'K_max' not in parameters:
        log.warning("'K_max' not found in parameters, trying to read from .inputs file")
        Kmax = read_input_float_field(input_file, 'DischargeInceptionStepper.limit_max_K')
        if Kmax is None:
            raise RuntimeError(f"'{input_file}' does not contain 'DischargeInceptionStepper.limit_max_K' field")
        log.info(f"Using Kmax={Kmax}")
    else:
        Kmax = parameters['K_max']

    report_data = parse_report_file(db_run_path / 'report.txt',
                                    ['+/- Voltage',
                                     'Max K(+)',
                                     'Max K(-)',
                                     'Pos. max K(+)',
                                     'Pos. max K(-)'])
    report_data = report_data[1]  # discard column names

    def pick_data(Kmin, Kmax, data):
        imin, iMax = (0, 0)
        for i, (_, K, _) in enumerate(data):
            if K <= Kmin:
                imin = i
            if K <= Kmax:
                iMax = i

        if data[iMax][1] != Kmax and iMax+1 < len(data):
            iMax += 1  # round to nearest K higher than Kmax
        return data[imin:iMax+1]

    table = []
    if polarity >= 0:
        table.extend(pick_data(Kmin, Kmax,
                               [(voltage, Kp, pos_p)
                                for voltage, Kp, _, pos_p, _ in report_data])
                     )
    if polarity <= 0:
        table.extend(pick_data(Kmin, Kmax,
                               [(voltage, Km, pos_n)
                                for voltage, _, Km, _, pos_n in report_data])
                     )

    # sort on voltage (ascending)
    sorted_table = sorted(table, key=lambda t: t[0])

    log.debug(sorted_table)
    enum_table = list(enumerate(sorted_table))

    output_prefix = "voltage_"

    MAX_BACKUPS = 10

    index_path = Path('index.json')
    # guard for reposting of the job
    backup_file(index_path, max_backups=MAX_BACKUPS)

    # write voltage index
    with open(index_path, 'w') as voltage_index_file:
        json.dump(dict(
            key=["voltage", "K", "particle_position"],
            prefix=output_prefix,
            index={i: item for i, item in enum_table}
            ),
                  voltage_index_file, indent=4)

    if not os.path.islink('jobscript_symlink'):
        # recreate the generic job-script symlink, so that the actual .sh jobscript work:
        os.symlink('generic_array_job_jobscript.py', 'jobscript_symlink')

    # create run directories, copy files, set voltage and particle positions, etc.
    for i, row in enum_table:
        voltage_dir = Path(f'{output_prefix}{i:d}')

        # don't delete old invocations
        backup_dir(voltage_dir, max_backups=MAX_BACKUPS)
        os.makedirs(voltage_dir, exist_ok=False)

        # further symlink program executable
        link_path = voltage_dir / 'program'
        if not link_path.is_symlink():
            os.symlink(Path('../program'), link_path)

        # grab original file names from structure
        required_files = [Path(f).name for f in structure['required_files']]
        copy_files(log, required_files, voltage_dir)

        # reuse the combination writing code from the configurator / config_util, by
        # building a fake combination and parameter space:
        particle_pos = [0.0, row[2][1], 0.0]  # strip X and Z coords
        comb_dict = dict(
                voltage=row[0],
                sphere_dist_props=[
                    particle_pos,  # center position
                    0.5*parameters['geometry_radius']  # half the tip's radius
                    ],
                single_particle_position=particle_pos# center position
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
                        'position'  # NB! two parameters
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

                array_job_id_path = Path('array_job_id')
                backup_file(array_job_id_path, max_backups=MAX_BACKUPS)

                with open(array_job_id_path, 'w') as job_id_file:
                    job_id_file.write(job_id)
                log.info(f"Submitted array job (for '{structure['identifier']}" +
                         f"_voltage' combination set). [slurm job id = {job_id}]")

        if p.poll() is not None:
            break
