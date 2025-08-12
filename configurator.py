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

from collections import defaultdict

from subprocess import Popen, PIPE
import argparse
import time

import os.path

import logging
import logging.handlers

from match_reaction import match_requirement, match_reaction

LOG_SPACER_STR = '-'*40
DEFAULT_OUTPUT_DIR_PREFIX = 'run_'

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

    def format_value(value):
        if isinstance(value, list):
            try:
                float(value[0])
                isfloat = True
            except:
                isfloat = False

            if isfloat:
                newvalue = " ".join([f'{v:g}' for v in value])
            else:
                newvalue = " ".join(value)
        else:
            newvalue = value
        return newvalue

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
                newline = f'{address}={value_whitespace}{format_value(comb_dict[key])}'
                newline_len = len(newline)
                if commentpos != -1:
                    if newline_len > commentpos:
                        newline += " " + comment
                    else:
                        newline += f'{" "*(commentpos-newline_len)}# ' + \
                                f'[script-altered]{comment[1:]}'
                line = newline
        sys.stdout.write(line)
    
    if not found_line:
        with open(input_file, 'a') as in_file:
            in_file.write(f"\n{pspace[key]['uri']} = {format_value(comb_dict[key])}"
                          " #[script-added]")

def handle_combination(keys, pspace, comb_dict):
    log = logging.getLogger(sys.argv[0])

    json_cache = {}
    for key in keys:
        target = Path(pspace[key]['target'])

        log.debug(f"key: {key}, target: {target}")

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


def copy_required_files(log, required_files, destination):
    """ Copy the required files to the destination
    """
    for file in required_files:
        shutil.copy(file, destination, follow_symlinks=True)
        log.debug(f'copying in file: {file}')


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

    copy_required_files(log, obj['required_files'], out_dir)

    log.info(LOG_SPACER_STR)

    return (out_dir, program)


def clean_definition(obj_def, keys, dim):
    """ clean the obj_def specification for absolute file paths.
    """
    d = dict(
            identifier = obj_def['identifier'],
            job_script = Path(obj_def['job_script']).name,
            program = Path(obj_def['program']).name,
            required_files = [Path(f).name for f in obj_def['required_files']],
            parameter_space = obj_def['parameter_space'],
            space_order = list(keys),
            dim = dim
            )
    
    output_dir_prefix = DEFAULT_OUTPUT_DIR_PREFIX
    if 'output_dir_prefix' in obj_def:
        output_dir_prefix = obj_def['output_dir_prefix']
    d['output_dir_prefix'] = output_dir_prefix

    return d


def setup_job_dir(log, obj, output_name_pattern, output_dir, i, combination):
    output_name = output_name_pattern.format(i=i)
    pspace = obj['parameter_space']
    keys = pspace.keys()
    comb_dict = dict(zip(keys, combination))
    log.debug(f'{output_name} --> {json.dumps(comb_dict)}')

    res_dir = output_dir / output_name
    os.mkdir(res_dir)  # yes, crash if you must

    # make a copy of required files to the run directory
    log.debug("Copying in required files.")
    req_files_in_run_dir = copy_required_files(log,
                                               obj['required_files'],
                                               res_dir)

    # Dump an json index file with the parameter space combination.
    # This might not be needed, as the values can be found from other input
    # files. Could be handy though when browsing and cataloguing the result sets.
    # Take note that the field keys are the variable names of the parameters, not
    # the actual URIs
    with open(res_dir / 'parameters.json', 'x') as index:
        json.dump(comb_dict, index, indent=4)

    cwd = os.getcwd()
    os.chdir(res_dir)
    # update the *.json and *.inputs target files in the run directory from the
    # parameter space

    handle_combination(keys, pspace, comb_dict)
    os.chdir(cwd)


def setup_database(log, database_definition, output_dir, dim):
    df = database_definition  # alias
    ident = df['identifier']

    db_dir, program = setup_env(log, database_definition, "database", output_dir, dim)

    pspace = df['parameter_space']
    # The parse order of json objects are not guaranteed, so keep track of the
    # order explicitly here:
    keys = list(pspace.keys())

    # store a copy of the parameter space used and the parse order of the keys,
    # so that this can be retrieved for postprocessing
    with open(db_dir / 'structure.json', 'x') as structure_file:
        json.dump(clean_definition(df, keys, dim), structure_file, indent=4)

    log.info(LOG_SPACER_STR)
    return keys, db_dir


def get_output_name_pattern(obj):
    output_dir_prefix = DEFAULT_OUTPUT_DIR_PREFIX
    if 'output_dir_prefix' in obj:
        odp = obj['output_dir_prefix']
        if not isinstance(odp, str):
            raise ValueError(f"'output_dir_prefix' in structure: {ident} is not a string'")
        output_dir_prefix = obj['output_dir_prefix']
    return output_dir_prefix+'{i:d}'

def setup_study(log, study, databases, output_dir, dim):

    ident = study['identifier']
    
    st_dir, program = setup_env(log, study, "study", output_dir, dim)

    pspace = study['parameter_space']  # alias used below
    keys = pspace.keys()

    log.info(f'Parameter order: {list(keys)}')
    combinations = list(get_combinations(pspace, keys))
    num_combs = len(combinations)
    
    log.info(f'Number of parameter space combinations: {num_combs}')

    num_jobs = num_combs
    if num_jobs > 1000:
        log.warning("The number of combinations > 1000 (sigma2 limit for "
                    "array slurm array jobs")

    output_name_pattern = get_output_name_pattern(study)
    log.info("Creating and populating working directories for array jobs")


    log.info("Study json written to study_index.json")
    # TODO: this contains absolute paths for the required files, program, job_script
    # etc., which is not ideal. Consider stripping this from the generated index file.
    with open(st_dir / 'study_index.json', 'x') as study_index:
        json.dump(clean_definition(study, keys, dim), study_index, indent=4)

    # generate combination directories
    for i, combination in enumerate(combinations):
        setup_job_dir(log, study, output_name_pattern, st_dir, i, combination)

    db_params = {}  # guaranteed to have the same order as 'keys' returned below
    for key, param_def in pspace.items():
        if 'database' in param_def:
            dbname = param_def['database']
            if not dbname in db_params:
                db_params[dbname] = []
            db_params[dbname].append(key)

    return keys, combinations, db_params

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

    # map database identifier to data, keys and sets of (undetermined)
    # combinations to run
    databases = {}
    if 'databases' in structure:
        for database in structure['databases']:
            missing_fields = verify_fields(database)
            if missing_fields:
                raise ValueError(f'database is missing fields: {missing_fields}')
            keys, db_dir = setup_database(log, database, output_dir, dim)

            # TODO: refactor from tuple to dict
            databases[database['identifier']] = (database, db_dir, keys, set())
    studies = {}
    for study in structure['studies']:
        missing_fields = verify_fields(study)
        if missing_fields:
            raise ValueError(f'study \'{study["identifier"]}\' is missing fields: {missing_fields}')
        keys, combinations, db_params = setup_study(log, study, databases, output_dir, dim)

        studies[study['identifier']] = dict(
                databases_deps=db_params.keys()
                )

        log.debug(f"keys: {keys}") 
        log.debug(f"combinations: {combinations}")

        # Given the combination list, sort the ranks according to the order in the
        # "database"
        #       -- Only one database is supported by this line of thinking --
        # and gather the combinations into job groups sharing the database parameters.

        for db_id, db_keys in db_params.items():
            # 1) find column indices of each db_params parameter set
            indices = [list(keys).index(k) for k in db_keys]

            if len(indices) != len(db_keys):
                raise RuntimeError(f'study \'{study["identifier"]}\' depends on '
                                   f'database \'{db_id}\' but does not utilize all '
                                   f'parameters ({len(db_keys)}.')

            db_structure, _, db_orig_keys, combination_set = databases[db_id]

            # in case the study referenced the parameters in a different order, resort
            order = get_sort_order(db_keys, db_orig_keys)
            keys_match_db = [db_keys[i] for i in order] == db_orig_keys
            log.debug(f"sort order: {order}")
            log.debug(f'reference keys match db parameters?: {keys_match_db}')

            # resort to original database order, see above
            sorted_indices = [indices[i] for i in order]
            
            # 2) extract subset of combinations for the database parameters
            db_combinations = {tuple(comb[i] for i in sorted_indices)
                                         for comb in combinations}
            log.debug(f'db \'{db_id}\', combs: {db_combinations}')

            # add to combination set for db
            combination_set.update(db_combinations)

            # NOT NEEDED now, but might be handy if one wants to parallelize slurm jobs
            # even further: groupby db_combinations
            # grouped_combinations = defaultdict(list)
            # for j,comb in enumerate(combinations):
            #     db_key = tuple(comb[i] for i in indices)
            #     # store the whole combinations with the original enumeration id
            #     # this id corresponds with the folder id of the combination generated by the
            #     # setup_study routine.
            #     grouped_combinations[db_key].append((j,comb))
            # log.debug(grouped_combinations)

        #schedule_array_jobs(log, study, afterok=db_job_ids)

    log.info(LOG_SPACER_STR)
    for db_id, db in databases.items():
        structure, db_dir, keys, combination_set = db
        sorted_combination_set = sorted(combination_set)
        job_id = schedule_db_jobs(log, structure, db_dir, sorted_combination_set)
    
    return


def get_sort_order(sl, l):
    """ Get the sorting order (indices) for list sl to match the order in l
    """
    return [i[0] for i in sorted(enumerate(sl), key=lambda x:l.index(x[1]))]


def schedule_db_jobs(log, structure, db_dir, sorted_combinations):
    num_jobs = len(sorted_combinations)
    if num_jobs < 1:
        raise ValueError('num_jobs < 1')

    # 1) register jobs in db directory index
    # TODO: utilizing an sqlite database or similar will simplify reruns and
    # registerring more.
    log.debug(f'registerring {num_jobs} db jobs')

    output_name_pattern = get_output_name_pattern(structure)

    log.debug('writing index file')
    with open(db_dir / 'index.json', 'x') as resind_file:
        json.dump({i:item for i,item in enumerate(sorted_combinations)}, resind_file, indent=4)

    for i, combination in enumerate(sorted_combinations):
        setup_job_dir(log, structure, output_name_pattern, db_dir, i, combination)

    job_name='inception_stepper'
    cmdstr = f'sbatch --array=0-{num_jobs-1} --chdir="{db_dir}" ' + \
        f'{structure["job_script"]}'
    log.debug(f'cmd string: \'{cmdstr}\'')
    p = Popen(cmdstr, shell=True, stdout=PIPE, encoding='utf-8')

    job_id = -1
    while True: # wait until sbatch is complete
        # try to capture the job id
        line = p.stdout.readline()
        if line:
            m = re.match('^Submitted batch job (?P<job_id>[0-9]+)', line)
            if m:
                job_id = m.groupdict()['job_id']
                with open(db_dir / 'inception_stepper_array_job_id', 'x') as job_id_file:
                    job_id_file.write(job_id)
                log.info(f"Submitted array job (over db '{job_name}' combination subset)."
                         f" [slurm job id = {job_id}]")

        if p.poll() is not None:
            break

    return job_id


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

    # set up database and study directory structures
    setup_result = setup(log, args.output_dir, args.run_definition, dim=args.dim,
                         verbose=args.verbose, dry_run=args.dry_run)



if __name__ == '__main__':
    main()
