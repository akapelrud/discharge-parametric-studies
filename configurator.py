#!/usr/bin/env python

import json
import itertools
import os
import shutil
from pathlib import Path
import importlib.util
import sys
import re

from config_util import (
        handle_combination, copy_files, get_output_prefix,
        DEFAULT_OUTPUT_DIR_PREFIX
        )

from subprocess import Popen, PIPE
import argparse

import os.path

import logging
import logging.handlers

LOG_SPACER_STR = '-'*40


def get_combinations(pspace, keys):
    return itertools.product(*[pspace[key]['values'] for key in keys])


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
    os.symlink(Path(obj['job_script']).name, out_dir / 'jobscript_symlink')

    program = obj['program'].format(DIMENSIONALITY=dim)

    shutil.copy(program, out_dir, follow_symlinks=True)
    log.info(f"  * program: {program}")

    if 'required_files' in obj:
        copy_files(log, obj['required_files'], out_dir)
    else:
        log.warning(f"no 'required_files' field in '{ident}'")

    if 'job_script_dependencies' in obj:
        copy_files(log, obj['job_script_dependencies'], out_dir)
    else:
        log.warning(f"no 'job_script_dependencies' field in '{ident}'")

    # store a copy of the parameter space used and the parse order of the keys,
    # so that this can be retrieved for postprocessing
    log.info("Structure json written to structure.json")
    keys = list(obj['parameter_space'].keys())
    with open(out_dir / 'structure.json', 'x') as structure_file:
        json.dump(clean_definition(obj, keys, dim), structure_file, indent=4)

    log.info(LOG_SPACER_STR)

    return (out_dir, program)


def clean_definition(obj_def, keys, dim):
    """ clean the obj_def specification for absolute file paths.
    """
    d = dict(
            identifier=obj_def['identifier'],
            program=Path(obj_def['program']).name,
            program_options=str(obj_def['program_options']) if 'program_options' in obj_def else '',
            job_script=Path(obj_def['job_script']).name,
            job_script_dependencies=[Path(f).name for f in obj_def['job_script_dependencies']] if 'job_script_dependencies' in obj_def else [],
            required_files=[Path(f).name for f in obj_def['required_files']],
            parameter_space=obj_def['parameter_space'],
            space_order=list(keys),
            dim=dim
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
    copy_files(log, obj['required_files'], res_dir)

    # create program symlink
    os.symlink(
            Path('..') / Path(obj['program'].format(DIMENSIONALITY=obj['dim'])).name,
            res_dir / 'program')

    # Dump an json file with the parameter space combination.
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
    handle_combination(pspace, comb_dict)
    os.chdir(cwd)


def setup_database(log, database_definition, output_dir, dim):
    df = database_definition  # alias

    db_dir, program = setup_env(log, df, "database", output_dir, dim)

    pspace = df['parameter_space']
    # The parse order of json objects are not guaranteed, so keep track of the
    # order explicitly here:
    keys = list(pspace.keys())
    return keys, db_dir


def setup_study(log, study, output_dir, dim):
    st_dir, program = setup_env(log, study, "study", output_dir, dim)

    pspace = study['parameter_space']  # alias used below
    keys = pspace.keys()

    log.info(f'Parameter order: {list(keys)}')
    combinations = list(get_combinations(pspace, keys))

    db_params = {}  # guaranteed to have the same order as 'keys' returned below
    for key, param_def in pspace.items():
        if 'database' in param_def:
            dbname = param_def['database']
            if dbname not in db_params:
                db_params[dbname] = []
            db_params[dbname].append(key)

    return keys, combinations, st_dir, db_params


def setup(log,
          output_dir,
          run_definition,
          structure=None,
          dim=3, verbose=False, dry_run=False):
    """ Parse the parameter space definition and create output directory structure for
    all combinations in the parameter space.
    """

    if structure is None:  # todo: merge structure and run_definition to one variable
        structure = parse_structure_from_input_file(run_definition)

    log.debug(structure)

    if 'studies' not in structure:
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
            if f not in d:
                missing_fields.append(f)
        return missing_fields

    # map database identifier to data, keys and sets of (undetermined)
    # combinations to run
    log.info(LOG_SPACER_STR)
    databases = {}
    if 'databases' in structure:
        for database in structure['databases']:
            database['dim'] = dim
            missing_fields = verify_fields(database)
            if missing_fields:
                raise ValueError(f'database is missing fields: {missing_fields}')
            keys, db_dir = setup_database(log, database, output_dir, dim)

            databases[database['identifier']] = dict(
                    structure=database,
                    directory=db_dir,
                    keys=keys,
                    combination_set=set())

    log.info(LOG_SPACER_STR)
    studies = dict()
    for study in structure['studies']:
        study['dim'] = dim
        missing_fields = verify_fields(study)
        if missing_fields:
            raise ValueError(f'study \'{study["identifier"]}\' is missing fields:' +
                             f'{missing_fields}')
        keys, combinations, st_dir, db_params = setup_study(log, study, output_dir, dim)

        studies[study['identifier']] = dict(
                structure=study,
                database_deps=db_params,
                directory=st_dir,
                keys=keys,
                combinations=combinations
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

            db_dict = databases[db_id]
            db_orig_keys = db_dict['keys']
            combination_set = db_dict['combination_set']

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

            # NOT NEEDED now, but might be handy if one wants to parallelize slurm job
            # and array dependencies.
            #
            # even further: groupby db_combinations
            # grouped_combinations = defaultdict(list)
            # for j,comb in enumerate(combinations):
            #     db_key = tuple(comb[i] for i in indices)
            #     # store the whole combinations with the original enumeration id
            #     # this id corresponds with the folder id of the combination
            #     # generated by the setup_study routine.
            #     grouped_combinations[db_key].append((j,comb))
            # log.debug(grouped_combinations)

    log.info(LOG_SPACER_STR)

    # fire of db slurm jobs
    for db_id, db in databases.items():
        db['job_id'] = schedule_slurm_jobs(log, db['structure'],
                                           db['directory'],
                                           sorted(db['combination_set']))
    log.info(LOG_SPACER_STR)

    # start dependent slurm array jobs
    for st_id, study in studies.items():
        log.debug(study)
        dep_joblist = []
        for db_id in study['database_deps'].keys():
            db = databases[db_id]

            log.debug(db['directory'].absolute())
            log.debug(study['directory'].absolute())

            os.symlink(
                    Path('..')/db['directory'].relative_to(study['directory'].parent),
                    study['directory'] / db_id,
                    target_is_directory=True)

            # add slurm dependency
            dep_joblist.append(db['job_id'])

        log.debug(f"deps: {dep_joblist}")
        schedule_slurm_jobs(log, study['structure'],
                            study['directory'],
                            study['combinations'],
                            afterok_joblist=dep_joblist)
    log.info(LOG_SPACER_STR)

    return


def get_sort_order(sort_list, orig_list):
    """ Get the sorting order (indices) for list sortlist to match the order in
    orig_list
    """
    return [i[0] for i in sorted(enumerate(sort_list),
                                 key=lambda x: orig_list.index(x[1]))]


def schedule_slurm_jobs(log, structure, out_dir, sorted_combinations,
                        afterok_joblist=None):
    num_jobs = len(sorted_combinations)
    if num_jobs < 1:
        raise ValueError('num_jobs < 1')
    elif num_jobs > 1000:
        log.warning("The number of combinations > 1000 (sigma2 limit for "
                    "array slurm array jobs")

    output_prefix = get_output_prefix(structure)
    output_name_pattern = output_prefix + '{i:d}'

    log.debug(f'registering {num_jobs} jobs')
    log.debug('writing index file')
    # 1) register jobs in db directory index
    # TODO: utilizing an sqlite database or similar will simplify reruns and
    # registering, as json cannot have tuple keys (python can)
    with open(out_dir / 'index.json', 'x') as resind_file:
        json.dump(dict(
            prefix=output_prefix,
            keys=list(structure['parameter_space'].keys()),
            index={i: item for i, item in enumerate(sorted_combinations)}
            ), resind_file, indent=4)

    for i, combination in enumerate(sorted_combinations):
        setup_job_dir(log, structure, output_name_pattern, out_dir, i, combination)

    cmdstr = f'sbatch --array=0-{num_jobs-1} --chdir="{out_dir}" ' + \
            f'--job-name="{structure["identifier"]}" '

    if afterok_joblist:
        cmdstr += f"--dependency=afterok:{','.join([str(j) for j in afterok_joblist])} "

    cmdstr += f'generic_array_job.sh'
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
                with open(out_dir / 'array_job_id', 'x') as job_id_file:
                    job_id_file.write(job_id)
                log.info(f"Submitted array job (for '{structure['identifier']}' "
                         f"combination set). [slurm job id = {job_id}]")

        if p.poll() is not None:
            break

    return job_id


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
                        help="Don't run any mpi simulations, only create folder "
                        "structures.")

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
    setup(log, args.output_dir, args.run_definition, dim=args.dim,
                         verbose=args.verbose, dry_run=args.dry_run)


if __name__ == '__main__':
    main()
