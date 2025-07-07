#!/usr/bin/env python

import json
import itertools
import os
import shutil
import sqlite3
from pathlib import Path
import importlib.util
import sys
import re
import fileinput

from subprocess import Popen, PIPE
import argparse
import time

import os.path

import logging
import logging.handlers

from match_reaction import match_requirement, match_reaction

LOG_SPACER_STR = '-'*40

def get_combinations(pspace, keys):
    return itertools.product(*[pspace[key]['values'] for key in keys])


def parse_commented_json_to_dict(filepath):
    """ Reads filepath line by line and strips all C++ style block (//) comments. Parse
    using json module and return contents as a dict.
    """
    json_content = []
    with open(filepath) as json_file:
        for line in json_file:
            json_content.append(line.partition('//')[0])  # strip comments
    return json.loads(''.join(json_content))


def set_nested_value(d, keys: list[str], value):
    """ Set the value for a nested dictionary hierarchy using a list of keys as the
    depth address
    """
    log = logging.getLogger(sys.argv[0])

    for key in keys[:-1]:
        if isinstance(d, list):  # here we have to search
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


def handle_json_combination(json_content, key, pspace, comb_dict):
    """ Write key value from comb_dict to the appropriate json uri
    """
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
        set_nested_value(json_content, uri,
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

    for line in fileinput.input(input_file, inplace=True):  # print() writes to file
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

def handle_combination(keys, pspace, comb_dict):
    log = logging.getLogger(sys.argv[0])

    json_cache = {}
    for key in keys:
        target = Path(pspace[key]['target'])

        match target.suffix:
            case '.json':
                json_content = None
                if target in json_cache:
                    json_content = json_cache[target]
                else:
                    json_content = parse_commented_json_to_dict(target)
                    json_cache[target] = json_content
                handle_json_combination(json_content, key, pspace, comb_dict)
            case '.inputs':
                handle_input_combination(target, key, pspace, comb_dict)
            case _:
                continue

    # write back all modified json caches
    for key, value in json_cache.items():
        with open(key, 'w') as json_file:
            json.dump(value, json_file, indent=4)


def parse_structure_from_input_file(run_definition_file: Path):
    """Read in the database and study definitions

    If the filename extension:

    *.json:
        parse json as dict
    *.py:
        look for global variable named 'top_object' and look for key-value pair
        'parameter_space':dict(...)
    """

    match run_definition_file.suffix:
        case '.json':
            with open(run_definition_file) as jsonfile:
                structure = json.load(jsonfile)
        case '.py':
            # https://docs.python.org/3/library/importlib.html#importing-a-source-file-directly
            module_name = 'run_definition'
            spec = importlib.util.spec_from_file_location(
                    module_name, run_definition_file)
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            # look for top object, might crap out
            structure = module.top_object
        case _:
            raise ValueError('Wrong filetype for option --parameter-space-file')
    return structure


def setup_database_index(log, con, keys, pspace):

    table_query = ["CREATE TABLE parameters (",
                   "id", *[f", {key} float" for key in keys],
                   ")"
                   ]
    query = "".join(table_query)
    log.debug(f"database table:\n{' '*4}{query}")
    con.execute(query)
    con.commit()
    pass


def copy_required_files(log, required_files, destination, verbose=True):
    """ Copy the required files to the destination
    """
    for file in required_files:
        shutil.copy(file, destination, follow_symlinks=True)
        log.info(f'copying in file: {file}')


def setup_env(log, obj, obj_type, output_dir, dim):
    """ Set up output directory and copy in required files, program and job_script
    """
    ident = obj['identifier']
    jobscript = obj['job_script']
    
    out_dir = output_dir / obj['output_directory']

    log.info(LOG_SPACER_STR)
    log.info(f"Setting up {obj_type} simulation: '{ident}'")

    os.makedirs(out_dir, exist_ok=False)  # yes, crap out if it exists
    log.info(f"  * directory: {out_dir}")

    shutil.copy(obj['job_script'], out_dir, follow_symlinks=True)
    log.info(f"  * job_script: {jobscript}")

    program = obj['program']
    try:
        program = program.format(DIMENSIONALITY=dim)
    except:
        pass  # ok. The program does not contain a template parameter
   
    shutil.copy( program, out_dir, follow_symlinks=True)
    log.info(f"  * program: {program}")

    copy_required_files(log, obj['required_files'], out_dir, verbose=True)

    log.info(LOG_SPACER_STR)

    return (out_dir, program)

def setup_database(log, database_definition, output_dir, dim):
    df = database_definition  # alias
    ident = df['identifier']

    db_dir, program = setup_env(log, database_definition, "database", output_dir, dim)

    pspace = df['parameter_space']
    # The parse order of json objects are not guaranteed, so keep track of the
    # order explicitly here:
    keys = pspace.keys()

    # store a copy of the parameter space used and the parse order of the keys,
    # so that this can be retrieved for postprocessing
    index = {
            'parameter_space': pspace,
            'space_order': list(keys),
            'dim': dim,
            }
    with open(db_dir / 'result_index.json', 'x') as resind_file:
        json.dump(index, resind_file, indent=4)

    log.info("creating sqlite3 index db and tables")
    con = sqlite3.connect(db_dir / 'index.db')
    setup_database_index(log, con, keys, pspace)
    
    log.info(LOG_SPACER_STR)
    return con


def setup_study(log, study, databases, output_dir, dim):

    ident = study['identifier']
    
    st_dir, program = setup_env(log, study, "study", output_dir, dim)

    pspace = study['parameter_space']  # alias used below
    keys = pspace.keys()

    log.info(f'Parameter order: {list(keys)}')
    combinations = list(get_combinations(pspace, keys))
    num_combs = len(combinations)
    
    log.info(f'Number of parameter space combinations: {num_combs}')
    num_digits = len(str(num_combs))

    num_jobs = num_combs
    if num_jobs > 1000:
        log.warning("The number of combinations > 1000 (sigma2 limit for "
                    "array slurm array jobs")

    output_dir_prefix = 'run_'
    if 'output_dir_prefix' in study:
        odp = study['output_dir_prefix']
        if not isinstance(odp, str):
            raise ValueError(f"'output_dir_prefix' in study: {ident} is not a string'")
        output_dir_prefix = study['output_dir_prefix']

    log.info("Creating and populating working directories for array jobs")
    output_name_pattern = '{output_prefix}{i:0{num_digits}d}'

    for i, combination in enumerate(combinations):

        output_name = output_name_pattern.format(
                output_prefix=output_dir_prefix, i=i, num_digits=num_digits)
        comb_dict = dict(zip(keys, combination))
        log.debug(f'{output_name} --> {json.dumps(comb_dict)}')

        res_dir = st_dir / output_name
        os.mkdir(res_dir)  # yes, crash if you must

        # make a copy of required files to the run directory
        req_files_in_run_dir = copy_required_files(log,
                                                   study['required_files'],
                                                   res_dir, verbose=True)

        # Dump an json index file with the parameter space combination.
        # This might not be needed, as the values can be found from other input
        # files. Could be handy though when browsing and cataloguing the result sets.
        with open(res_dir / 'parameters.json', 'x') as index:
            json.dump(comb_dict, index, indent=4)

        cwd = os.getcwd()
        os.chdir(res_dir)
        # update the *.json and *.inputs target files in the run directory from the
        # parameter space
        handle_combination(keys, pspace, comb_dict)
        os.chdir(cwd)

def setup(log,
          output_dir,
          run_definition,
          structure = None,
          dim=3, verbose=False, dry_run=False):
    """ Parse the parameter space definition and create output directory structure for
    all combinations in the parameter space.
    """

    if structure is None:  # todo: merge structure and run_definition to one variable
        structure = parse_structure_from_input_file(run_definition)

    log.debug(structure)

    if not 'studies' in structure:
        raise ValueError('No studies present in run definition')

    if not isinstance(structure['studies'], list):
        raise ValueError("'studies' should be a list")
    
    log.debug(f"Creating output directory '{output_dir}' (if not exists)")
    os.makedirs(output_dir, exist_ok=False)  # yes, crap out if it exists

    def verify_fields(d):
        """ Just verify the existence of a constant set of required field keys
        """
        required_fields = {
                'identifier', 'job_script', 'required_files', 'parameter_space',
                'program'
                }
        missing_fields = []
        for f in required_fields:
            if not f in d:
                missing_fields.append(f)
        return missing_fields

    databases = {}  # map database identifier to sqlite connection
    if 'databases' in structure:
        for database in structure['databases']:
            missing_fields = verify_fields(database)
            if missing_fields:
                raise ValueError(f'database is missing fields: {missing_fields}')
            con = setup_database(log, database, output_dir, dim)
            databases[database['identifier']] = con

    for study in structure['studies']:
        missing_fields = verify_fields(study)
        if missing_fields:
            raise ValueError(f'study is missing fields: {missing_fields}')
        setup_study(log, study, databases, output_dir, dim)

    return

def schedule_array_jobs(log, job_name, job_script, run_dir, num_jobs=-1, dry_run = False):
    
    if num_jobs < 1:
        raise ValueError('num_jobs < 1')

    job_name='inception_stepper'
    cmdstr = f'sbatch --array=0-{num_jobs-1} --chdir="{run_dir}" ' + \
        f'--job-name={job_name} inception_stepper.py'
    p = Popen(cmdstr, shell=True, stdout=PIPE, encoding='utf-8')

    job_id = -1
    while True: # wait until sbatch is complete

        # try to capture the job id
        line = p.stdout.readline()
        if line:
            m = re.match('^Submitted batch job (?P<job_id>[0-9]+)', line)
            if m:
                job_id = m.groupdict()['job_id']
                with open(run_dir / 'inception_stepper_array_job_id', 'x') as job_id_file:
                    job_id_file.write(job_id)
                log.info("Submitted array job (_inception stepper_ over all combinations)."
                         f" [slurm job id = {job_id}]")

        if p.poll() is not None:
            break

def main():
    parser = argparse.ArgumentParser(
            description="Batch script for mapping out streamer integral conditions")
    parser.add_argument("--verbose", action="store_true", help="increase verbosity")
    parser.add_argument("--logfile", default="configurator.log", help="log file")

    # output arguments
    parser.add_argument("--output-dir", default="study_results", type=Path,
                        help="output directory for study result files")

    # input file arguments
    parser.add_argument("run_definition",
                        default=Path("run_definition.json"),
                        type=Path, help="parameter space input file. "
                        "Json read directly, or if .py file look for 'top_object' "
                        "dictionary")

    # run options
    parser.add_argument("--dim", default=3, type=int,
                        help="dimensionality of simulations")
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't run any mpi simulations, only create folder structures.")

    args = parser.parse_args()

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

    # set up array job directory structures

    setup_result = setup(log, args.output_dir, args.run_definition, dim=args.dim,
                         verbose=args.verbose, dry_run=args.dry_run)

if __name__ == '__main__':
    main()
