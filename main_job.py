#!/usr/bin/env python

#SBATCH --job-name=inception_stepper
#SBATCH --account=nn12041k
#SBATCH --nodes=4
#SBATCH --ntasks-per-node=128
#SBATCH --time=

import json
import itertools
import os
import shutil
from pathlib import Path
import importlib.util
import sys
import re
import fileinput

from subprocess import Popen
import argparse
import time

import os.path

import logging
import logging.handlers

from match_reaction import match_requirement, match_reaction


def find_electron_placement(log, args):
    # --------------------------------------------------------------------------
    # run variables
    # --------------------------------------------------------------------------
    executable = "program2d.Linux.64.mpic++.gfortran.OPTHIGH.MPI.ex"
    exec_folder = "Vessel"
    # --------------------------------------------------------------------------

    nump = 2

    commands = [
            f"cp master.inputs {exec_folder}/",
            f"cd {exec_folder}",
            f"mpirun -np {nump:d} {executable} master.inputs "
            ]
    cmd = '; '.join(commands)
    log.info(f"$ {cmd}")
    p = Popen(cmd, shell=True)
    # todo: We might want to store i.e. stderr output to the log file.

    time.sleep(1)  # give the simulation time to start writing to pout.0:
    while True:
        res = p.poll()
        if res is not None:
            break

    # parse_report_file()


def step_sic(log, np, args):
    # --------------------------------------------------------------------------
    # run variables
    # --------------------------------------------------------------------------
    executable = "program2d.Linux.64.mpic++.gfortran.OPTHIGH.MPI.ex"
    sic_folder = "StreamerIntegralCriterion"

    # --------------------------------------------------------------------------

    potential_vals = []
    for potential in potential_vals:
        log.info('-'*40)
        log.info(f'Potential: {potential} V')

        output_directory = f"sic_{potential}"
        commands = [
                f"cp master.inputs {sic_folder}/",
                f"cd {sic_folder}",
                f"mpirun -np {np:d} {executable} master.inputs "
                f"StreamerIntegralCriterion.potential = {potential} "
                f"Driver.output_directory = {output_directory}"
                ]
        cmd = '; '.join(commands)
        log.info(f"$ {cmd}")
        p = Popen(cmd, shell=True)
        # todo: We might want to store i.e. stderr output to the log file.

        time.sleep(1)  # give the simulation time to start writing to pout.0:
        with open(f'{sic_folder}/pout.0') as pout:
            while True:
                res = p.poll()
                if res is not None:
                    break

                lines = pout.readlines()
                ts_progress = None
                for line in lines:
                    if line.endswith('percentage of time steps completed\n'):
                        ts_progress = float(line.strip()[3:].split()[0])
                    elif line.endswith('percentage of simulation time completed\n'):
                        sim_progress = float(line.strip()[3:].split()[0])
                        log.info(f'ts: {ts_progress}% / sim: {sim_progress}%')
                time.sleep(1)

        if res != 0:
            log.error(f'mpirun exited with return code: {res:d}')
        else:
            log.info('Test run complete')


def get_combinations(pspace, keys):
    return itertools.product(*[pspace[key]['values'] for key in keys])


def get_chemistry_dict(filepath):
    chemistry_content = []
    with open(filepath) as chem_file:
        for line in chem_file:
            chemistry_content.append(line.partition('//')[0])
    return json.loads(''.join(chemistry_content))


def set_nested_value(d, keys: list[str], value):
    """ Set the value for a nested dictionary hierarchy using a list of keys as the
    depth address
    """
    log = logging.getLogger(sys.argv[0])

    for key in keys[:-1]:
        if isinstance(d, list):
            if not (key.startswith('+[') or key.startswith('*[')):
                raise RuntimeError('no requirement found for matching to list '
                                   f'element for key: {key}')
            md = match_requirement(key)
            if not md:
                raise ValueError(f'match requirement: \"{key}\" is malformed')

            found_requirement = False
            for element in d:
                if not isinstance(element, dict):
                    log.warning('found non-dict/object in list when trying to match '
                                'requirement. Skipping element.')
                    continue

                if not md['field'] in element:
                    continue

                match md['type']:
                    case 'chem_react':
                        found_requirement = match_reaction(
                                md['value'], element[md['field']])
                    case _:
                        found_requirement = element[md['field']] == md['value']

                if found_requirement:
                    d = element
                    break

            if not found_requirement:
                if key[0] == '+':  # non-optional requirement
                    raise RuntimeError('missing list element has requirement')

                d.append({md['field']: md['value']})
                d = d[-1]

        else:
            d = d.setdefault(key, {})  # Create nested dicts if they don't exist
    d[keys[-1]] = value  # set the leaf node value


def expand_uri(uri, disparate=False, level=0):
    res = []
    if isinstance(uri, list):
        for uri_elem in uri:
            if disparate:
                disparate_exp_res = expand_uri(uri_elem, False, level)
                if isinstance(disparate_exp_res[0], list):
                    for r in disparate_exp_res:
                        res.append(r)
                else:
                    res.append(disparate_exp_res)
            else:
                parent_is_list = len(res) > 0 and isinstance(res[0], list)
                if not isinstance(uri_elem, list):
                    if parent_is_list:
                        for i in range(len(res)):
                            res[i].append(uri_elem)
                    else:
                        res.append(uri_elem)
                else:
                    # check for nested lists
                    if level > 0 and isinstance(uri_elem, list):
                        for sub in uri_elem:
                            if isinstance(sub, list):
                                raise ValueError("Nested lists are not allowed beyond "
                                                 "the 3rd level")
                    sub_tree = expand_uri(uri_elem, level=level+1)
                    tree_res = []
                    for tree in sub_tree:
                        if parent_is_list:
                            for i in range(len(res)):
                                tree_res.append([*res[i], tree])
                        else:
                            tree_res.append([*res, tree])
                    res = tree_res
    else:
        res.append(uri)

    if level == 0 and len(res) and not isinstance(res[0], list):
        res = [res]
    return res

def handle_chemistry_combination(chemistry, key, pspace, comb_dict):
    disparate = 'disparate' in pspace[key] and pspace[key]['disparate']
    expanded_uri = expand_uri(pspace[key]['uri'], disparate=disparate)
    dims = len(expanded_uri)

    if dims > 1:
        if not isinstance(comb_dict[key], list):
            raise ValueError(f"requirement '{pspace[key]['uri']}' has dims>1 "
                             "but value is a scalar")
        elif dims != len(comb_dict[key]):
            raise ValueError("requirement uri has different dimensionality "
                             "than value field")
    for i, uri in enumerate(expanded_uri):
        set_nested_value(chemistry, uri,
                         comb_dict[key] if dims == 1 else comb_dict[key][i])


def handle_input_combination(input_file, key, pspace, comb_dict):
    """
    warning: writes directly to input_file, search and replace mode
    """
    if not 'uri' in pspace[key]:
        raise ValueError(f'No uri for input requirement: {key}')
    if not isinstance(pspace[key]['uri'], str):
        raise ValueError(f'input requirement can only be a scalar string: {key}')
    if pspace[key]['uri'] == "":
        raise ValueError(f'empty uri string for: {key}')
    uri = pspace[key]['uri']

    found_line = False

    for line in fileinput.input(input_file, inplace=True):  # every print writes to file
        if not found_line and line.startswith(pspace[key]['uri']):
            content = line
            commentpos = content.find('#')
            comment = ""
            if commentpos != -1:
                comment = line[commentpos:]
                content = line[:commentpos]

            eq_pos = content.find('=')
            if eq_pos == -1:
                continue
            address = content[:eq_pos]
            value = content[eq_pos+1:]
            
            value_whitespace = re.match(r'\s*', value).group()

            if address.strip() == uri:
                found_line = True
                if isinstance(comb_dict[key], list):
                    try:
                        float(comb_dict[key][0])
                        isfloat = True
                    except:
                        isfloat = False

                    if isfloat:
                        newvalue = " ".join([f'{v:g}' for v in comb_dict[key]])
                    else:
                        newvalue = " ".join(comb_dict[key])
                else:
                    newvalue = comb_dict[key]
                newline = f'{address}={value_whitespace}{newvalue}'
                newline_len = len(newline)
                if commentpos != -1:
                    if newline_len > commentpos:
                        newline += " " + comment
                    else:
                        newline += f'{" "*(commentpos-newline_len)}# ' + \
                                f'[script-altered]{comment[1:]}'
                line = newline
        sys.stdout.write(line)

def handle_combination(keys, pspace, comb_dict, chemistry, input_file):
    log = logging.getLogger(sys.argv[0])
    for key in keys:
        match pspace[key]['target']:
            case 'chemistry':
                handle_chemistry_combination(chemistry, key, pspace, comb_dict)
            case 'input':
                handle_input_combination(input_file, key, pspace, comb_dict)
            case _:
                continue

def main():
    parser = argparse.ArgumentParser(
            description="Batch script for mapping out streamer integral conditions")
    parser.add_argument("--verbose", action="store_true", help="increase verbosity")
    parser.add_argument("--logfile", default="master.log", help="log file")
    parser.add_argument("--output-dir", default="results", type=Path,
                        help="output directory for result files")
    parser.add_argument("--chemistry-file", default=Path("chemistry.json"),
                        type=Path, help="chemistry input file")
    parser.add_argument("--parameter-space-file",
                        default=Path("parameter_space.json"),
                        type=Path, help="parameter space input file. "
                        "Json read directly, or if .py file look for 'pspace' "
                        "dictionary")
    parser.add_argument("--master-input-file",
                        default=Path("master.inputs"), type=Path,
                        help="master input file for chombo-discharge")
    parser.add_argument("--array-job-prefix", default='run_', type=str,
                        help="prefix for subdirectories in the 'output-dir'")
    args, unknownargs = parser.parse_known_args()

    log = logging.getLogger(sys.argv[0])
    formatter = logging.Formatter(
            '%(asctime)s | %(levelname)s :: %(message)s')
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(formatter)
    log.addHandler(sh)

    doroll = os.path.isfile(args.logfile)
    fh = logging.handlers.RotatingFileHandler(
            args.logfile, backupCount=5, encoding='utf-8')
    fh.setFormatter(formatter)
    log.addHandler(fh)
    log.setLevel(logging.INFO if not args.verbose else logging.DEBUG)

    if doroll:
        fh.doRollover()

    # read in the parameter space to be mapped
    match args.parameter_space_file.suffix:
        case '.json':
            with open(args.parameter_space_file) as jsonfile:
                pspace = json.load(jsonfile)['parameter_space']
        case '.py':
            # https://docs.python.org/3/library/importlib.html#importing-a-source-file-directly
            module_name = 'param_space'
            spec = importlib.util.spec_from_file_location(
                    module_name, args.parameter_space_file)
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            # assume there is a global variable dictionary with the name "pspace" in
            # said module
            pspace = module.pspace
        case _:
            raise ValueError('Wrong filetype for option --parameter-space-file')

    # The parse order of json objects are not guaranteed, so keep track of the
    # order explicitly here.
    keys = pspace.keys()

    log.debug("Creating output directory (if not exists)")
    os.makedirs(args.output_dir, exist_ok=False)  # yes, crap out if it exists

    # store a copy of the parameter space used and the parse order of the keys,
    # so that this can be retrieved for postprocessing
    index = {
            'parameter_space': pspace,
            'keys_output_order': list(keys),
            'job_prefix': args.array_job_prefix
            }

    with open(args.output_dir / 'result_index.json', 'x') as resindfile:
        json.dump(index, resindfile, indent=4)

    log.info(f'Parameter order: {list(keys)}')
    combinations = list(get_combinations(pspace, keys))
    num_combs = len(combinations)
    log.info(f'Number of parameter space combinations: {num_combs}')
    num_digits = len(str(num_combs))

    chemistry = get_chemistry_dict(args.chemistry_file)

    log.info("Creating and populating working directories for array jobs")
    output_name_pattern = '{job_prefix}{i:0{num_digits}d}'

    for i, combination in enumerate(combinations):

        output_name = output_name_pattern.format(job_prefix=args.array_job_prefix, i=i,
                                                 num_digits=num_digits)
        comb_dict = dict(zip(keys, combination))
        log.debug(f'{output_name} --> {json.dumps(comb_dict)}')

        res_dir = args.output_dir / output_name
        os.mkdir(res_dir)  # yes, crash if you must

        run_input = res_dir / 'run.inputs'
        shutil.copy(args.master_input_file, run_input)

        # Dump an json index file with the parameter space combination.
        # This might not be needed, as the values can be found from other input
        # files. Will be handy when browsing and cataloguing the result sets.
        with open(res_dir / 'index.json', 'x') as index:
            json.dump(comb_dict, index, indent=4)

        # update the chemistry and input specification
        # Deepcopying of chemistry should not be necessary, as all the
        # combination's fields are written every time in this loop.
        handle_combination(keys, pspace, comb_dict, chemistry, run_input)
        
        with open(res_dir / 'chemistry.json', 'x') as run_chem:
            json.dump(chemistry, run_chem, indent=4)
        
        # copy in the rest of the resources
        shutil.copy('bolsig_air.dat', res_dir)
        shutil.copy('transport_data.txt', res_dir)

    # we now now the number of combination runs to perform, the next task is to
    # determine the number of voltages to calculate. Robert need's to do his magic

    # For each combination a inception stepper run is needed followed by
    # the voltages as specified in the master.inputs file:
    #     DischargeInceptionStepper.voltage_lo    = 10E3
    #     DischargeInceptionStepper.voltage_hi    = 30E3
    #     DischargeInceptionStepper.voltage_steps = 9
    #
    # where the number of voltages tested is voltage_steps+2

    # it should be possible to run sbatch inside of an sbatch script
    num_jobs = num_combs
    job_name='inception_stepper'

    cmdstr = f'sbatch --array=1-{num_jobs} --chdir={args.output_dir}
    --job-name={job_name} inception_stepper.py'
    p = Popen(cmdstr, shell=True, stdout=PIPE, encoding='utf-8')

    job_id = -1
    while True: # wait until sbatch is complete
        line = p.stdout.readline()
        if line:
            m = re.match('^Submitted batch job (?P<job_id>[0-9]+)', line)
            if m:
                job_id = m.groupdict()['job_id']

        if p.poll() is not None:
            break

    if job_id != -1:
        log.info("Submitted array job (inception stepper over combinations)."
                 f" [slurm job id = {job_id}")
    {job_id}

if __name__ == '__main__':
    main()
