.. Discharge Parametric Studies documentation master file, created by
   sphinx-quickstart on Tue Feb  3 14:16:40 2026.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Discharge Parametric Studies
****************************
This page contains documentation for a collection of python and bash/slurm scripts for running multilevel chombo-discharge studies over wide parameter spaces.

.. This is for getting rid of the TOC in html view.
    .. raw:: html

        <style>
        section#introduction,
        section#design,
        section#tutorial,
        section#epilogue {
        display:none;
        }
        </style>   

.. only:: latex

    .. toctree::
       :caption: Contents

.. only:: html

        .. toctree::
           :maxdepth: 3
           :caption: Contents

Introduction / Usage
********************

Basic Usage
===========
The ``configurator.py`` script can be used to set up directory structures and submit slurm jobs for wide parametric sweeps over chombo-discharge based studies.

.. code-block::
   :caption: Invocation options
    $ python configurator.py --help

    usage: configurator.py [-h] [--verbose] [--logfile LOGFILE] [--output-dir OUTPUT_DIR]
                           [--dim DIM]
                           run_definition

    Batch script for running user-defined, parametrised chombo-discharge studies.

    positional arguments:
      run_definition        parameter space input file. Json read directly, or if .py file look
                            for 'top_object' dictionary

    options:
      -h, --help            show this help message and exit
      --verbose             increase verbosity
      --logfile LOGFILE     log file. (Postfix) Rotated automatically each invocation.
      --output-dir OUTPUT_DIR
                            output directory for study result files
      --dim DIM             Dimensionality of simulations. Must match chombo-discharge
                            compilation.

The most important part is the ``run_definition``, which is either structured as a json file or python file. If it is a python file it is dynamically imported and the object ``top_object`` (a dictionary) is loaded. A python dictionary containing basic types (sub-dictionaries, lists, strings, numbers, booleans) almost has the same syntax structured JSON data, and it is easy to use the json module to dump such a dictionary to a json file if needed. There are benefits for keeping your `run_definition` as a .py file though, e.g. the possibility to use variables when setting up the project structure or specifying numerical parameter ranges.

Overall Design
==============
.. toctree::
   :maxdepth: 3
   :caption: Design
   :hidden:

This piece of software parses a run definition dictionary/JSON structure that is comprised of *databases* and *studies*.

.. code-block:: python
   :caption: config_concept.py

    db_study = {
        ...
    }

    main_study = {
        ...
    }

    top_object = dict(
            databases=[db_study],
            studies=[main_study]
            )

The difference between a *database* and a *study* is mainly a semantic one; a study can depend on database, and the configurator will create and submit a slurm job hierarchy as well as create an output file hierarchy that reflects this.

A database is meant to be used as a first simulation step running specific (perhaps light-weight) jobs (chombo-discharge simulations, or other software) to generate intermediate data that the main studies depend on.

Each database or study step relies on running a (chombo-discharge) executable repeatedly, and often in parallel, over a defined parameter set. Ex.: if a parameter *pressure* should be varied over 5 different values, and another parameter *radius* should be varied over 3 different values, the parameter space would require 15 distinct runs. Now, the preliminary database study might only depend on the *pressure*, while the whole main study depends on both parameters. This would result in 5 jobs (submitted as parallel array job to slurm) for the database study, **followed** by 15 jobs (parallel, and depending on the success of the first database's array job) for the main study.


Run Definition
==============

A database/study will have these configurable fields:

* ``identifier``
* ``program``, executable to run
* ``output_directory``, relative to the cmdline output directory, i.e.  ``--output-dir``
* ``output_dir_prefix`` (default: ``"run_"``)
* ``job-script``,
* ``job_script_dependencies``
* ``required_files``
* ``parameter_space``, a dictionary of parameters to vary

The difference between ``job_script_dependencies`` and ``required_files`` is that the ``required_files`` will be copied into the bottom-level directory where the program is run from, i.e. into every specific *run* directory for every invocation over the parameter space.

- ``required_files`` is typically used for ``*.inputs`` chombo-discharge files, physical/chemical input files like ``*.json`` files, or other plain data files. Sometimes extra python modules or bash-scripts might be needed at the run-level, so use this field to copy those dependencies in.
- ``job_script_dependencies``, as the name implies, should point to whatever code is needed to configure and submit the actual slurm jobs.

The ``configurator.py`` script will set up directory structures and copy files into place, then launch slurm array jobs over all the configured parameter space referenced in each database. Then the same is repeated for the second-level studies. These second-level slurm array jobs are made dependent on the database jobs, essentially securing that they are run in sequence.

.. important::

   It is up to the `job_script` to submit the actual slurm jobs. Facilities are in place to translate a given slurm array job id/index into the correct parameter values.

.. code-block:: python
   :caption: directory structure example

    inception_stepper = {
        'identifier': 'inception_stepper',
        'output_directory': 'is_db',
        'program': 'program{DIMENSIONALITY}d.Linux.64.mpic++.gfortran.OPTHIGH.MPI.ex',
        'job_script': 'discharge_inception_jobscript.py',
        'job_script_dependencies': [
            'generic_array_job.sh',
            'parse_report.py',
            ...
            ],
        'required_files': [
            'master.inputs',
            'transport_data.txt'
            ],
        'parameter_space': {
            ...
            }
        }

    plasma_study = {
        'identifier': 'photoion',
        'output_directory': 'study0',
        'program': 'program{DIMENSIONALITY}d.Linux.64.mpic++.gfortran.OPTHIGH.MPI.ex',
        'job_script': 'plasma_jobscript.py',
        'job_script_dependencies': [
            'generic_array_job.sh',
            ...
            ],
        'required_files': [
            'master.inputs',
            'chemistry.json',
            'detachment_rate.dat',
            'electron_transport_data.dat'
            'Analyze.py',
            ],
        'parameter_space': {
            ...
            }
        }

    top_object = dict(
            databases=[inception_stepper],
            studies=[plasma_study]
            )

The example above has a more realistic structure. How the parameter spaces are defined can be found in a later section.

Note the use of a templated filename for the ``program`` field, where the part ``"{DIMENSIONALITY}"`` is exchanged with the dimension specified on the command line using the ``--dim`` flag.

Just after issuing this command, when the first slurm job for the database named *'inception_stepper'* has just started in the subdirectory ``run_0``, the resulting file hierarchy from this could look like:

.. code-block:: bash

    
    $ ls -R --file-type output-dir
    .:
    is_db/  study0/

    ./is_db:
    array_job_id                      jobscript_symlink@                                 run_0/
    discharge_inception_jobscript.py  master.inputs                                      structure.json
    generic_array_job.sh              parse_report.py                                    transport_data.txt
    index.json                        program3d.Linux.64.mpic++.gfortran.OPTHIGH.MPI.ex

    ./is_db/run_0:
    chk/    geo/           mpi/             plt/    pout.1  pout.3  program@  restart/
    crash/  master.inputs  parameters.json  pout.0  pout.2  pout.4  regrid/   transport_data.txt

    ./study0:
    Analyze.py                   generic_array_job.sh  parse_report.py
    array_job_id                 inception_stepper@    plasma_jobscript.py
    chemistry.json               index.json            program3d.Linux.64.mpic++.gfortran.OPTHIGH.MPI.ex
    config_util.py               jobscript_symlink@    run_0/
    detachment_rate.dat          json_requirement.py   structure.json
    electron_transport_data.dat  master.inputs

    ./study0/run_0:
    Analyze.py      detachment_rate.dat          generic_array_job.sh  parameters.json
    chemistry.json  electron_transport_data.dat  master.inputs         program@

Do notice:

* The rather self-explainatory named ``jobscript_symlink`` symlink pointing to the jobscripts:

    .. code-block:: bash

        output-dir/is_db$ readlink jobscript_symlink
        discharge_inception_jobscript.py

        output-dir/study0$ readlink jobscript_symlink
        plasma_jobscript.py

* The ``study0/inception_stepper`` symlink pointing across the file hierarchy:

    .. code-block:: bash
        
        output-dir/study0$ readlink inception_stepper
        ../is_db

* The ``program`` symlinks in the *"run_*"* sub-directories. These point to the actual executable in their respective parent directories.

    .. code-block:: bash

        output-dir/is_db/run_0$ readlink program
        ../program3d.Linux.64.mpic++.gfortran.OPTHIGH.MPI.ex

* For each database/study there are certain metadata files that are generated to make it possible to programatically traverse the created file-hierarchy from within the jobscripts or from within post-simulation analysis scripts. A job-script typically receives an array job index from slurm (through the environment variable ``$SLURM_ARRAY_TASK_ID``), and must use this to find the relevant parameters, dependent databases, get structural metadata and enter its own run-subdirectory and execute code there. These files becomes especially imortant when the second-level studies have to traverse the databases' result hierarchies to retrieve and parse database results before launching their own slurm jobs.

    .. note::
    
        Sometimes, one need to manipulate simulation input files directly from the job-scripts, e.g. to change some parameter depending on a *database* result. Python utility functions are provided to manipulate configuration files on-the-fly in this intermediate step.

    Generated files:

    * ``array_job_id`` containing a single integer; the slurm array job id for the this database/study
    * ``index.json``, containing a mapping between specific array job indices and all parameter sets for this database/study
    * ``structure.json`` a parsed dump of the overall structure of the database/study. This matches a parsed export of the corresponding section in the original `run_definition`. Included both for data consistency and for usage by the jobscripts to get extra metadata for setting up batch jobs.
    * ``run_*/parameters.json`` containing the actual parameter space point for that run.


The `configurator.py` script contains helper code to in-place manipulate both `.*inputs` files (normally used to specify chombo-discharge parameters), as well as generic structured `.json` files (e.g. used by chombo-discharge or physical/chemical data input.

Defining Parameter Spaces
-------------------------

Continuing the example from the previous section:

.. code-block:: python
    :caption: directory structure example

    inception_stepper = {
        'identifier': 'inception_stepper',
        'output_directory': 'is_db',
        ..
        'parameter_space': {
            "pressure": {
                "target": "master.inputs",
                "uri": "DischargeInception.pressure"
                },
            "geometry_radius": {
                "target": "master.inputs",
                "uri": "Rod.radius",
                },
            }
        }

    plasma_study = {
        'identifier': 'photoion',
        'output_directory': 'study0',
        ...
        'parameter_space': {
            "geometry_radius": {
                "database": "inception_stepper",  # database dependency
                "target": "master.inputs",
                "uri": "Rod.radius",
                "values": [1e-3, 2e-3, 3e-3]
                },
            "pressure": {
                "database": "inception_stepper",  # database dependency
                "target": "chemistry.json",
                "uri": ["gas", "law", "ideal_gas", "pressure"],
                "values": np.arange(1e5, 11e5, 1e5).tolist()
                },
            "photoionization": {
                "target": "chemistry.json",
                "uri": [
                    "photoionization",
                    [
                        '+["reaction"=<chem_react>"Y + (O2) -> e + O2+"]',  # non-optional match
                        '*["reaction"=<chem_react>"Y + (O2) -> (null)"]'  # optional match (create-if-not-exists)
                        ],
                    "efficiency"
                    ],
                "values": [[1.0, 0.0]]  #[[float(v), float(1.0-v)] for v in np.arange(0.0, 1.0, 1.0)]
                },
            }
        }

    top_object = dict(
            databases=[inception_stepper],
            studies=[plasma_study]
            )

The actual parameter values are typically specified for the top study definition, not the databases. The database only specifies where changes are to be made for a given value.

In this example there are several distinctly named parameters changing different aspects of the simulations:

* ``geometry_radius``:

    Marked as dependent on the database; meaning that this study will run after the database study.

    .. important::
    
        Both the database and the study has the same ``target`` file name and ``uri`` field, namely the ``master.inputs`` chombo-discharge input file and its ``Rod.radius`` field. Note that these are now different files residing within the output directory file hierarchy.

    This parameter contributes a factor 3 to the overall parameter space size.

* ``pressure``:

    List of values (Evaluates to ``[100000.0, 200000.0, ..., 900000.0, 1000000.0]``).

    The database will write this parameter to the ``master.inputs`` file by changing the ``DischargeInception.pressure`` (uri-field) input parameter, while the study has a different target, utilizing the json-writing capabilities to change the ``pressure`` field in the json hierarchy according to the list in the uri-field.
    
    This parameter contributes a factor 10 to the overall parameter space size.
    
* ``photoionization``:
    
    This is the most complex parameter. It only affects the ``chemistry.json`` target in the study.

    As can be seen in the uri specification the second level is a list of length 2. This means that this parameter changes two fields in ``chemistry.json`` at the same time. Similarly, the ``values`` field is a double list, where the first element of each contained list will be written to the uri of the first target field and the second element of each contained list will be written to the uri of the second target field.

    This, the value ``[[1.0, 0.0]]`` is to be regarded as a scalar quantity in the parameter space, and this parameter contributes a factor 1 to the overall parameter space size (not really affecting it).
    
    The resulting change for the runs in `study0/run_*/chemistry.json` will be:

    .. code-block::
        :caption: "resulting chemistry.json"

        {
            ...
            "photoionization": [
                {
                    "reaction": "Y + (O2) -> e + O2+",
                    "efficiency": 1.0
                },
                {
                    "reaction": "Y + (O2) -> (null)",
                    "efficiency": 0.0
                }
            ],
            ...
        }

    For the special syntax encountered see :ref:`navigating_json`.

.. _navigating_json:

Navigating JSON object hierarchies
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. note::
    The special syntax ``+["field-name"="search-value"]`` and ``*["field-name"="search-value"]`` is used to search a json list for an child object ``{...}`` containing a specific member ``"field-name"`` with a specific value "search-value".

    * ``+[]`` requires the object with the member ``field-name`` to exist.
    * ``*[]`` will create the object with the member ``field-name`` if it doesn't exist.

.. note::
   If searching for an on a list where the search key itself is an JSON object, ``search-value`` can be omitted: ``+["fields-name"]``. Remember to repeat the ``fields-name`` in your uri as the next list element to select that child object if needed.

.. note::
    The special notation ``<chem_react>`` is a hint to the parser that the value searched for in this specific example should be a valid chombo-discharge chemical reaction, c.f. `"Specifying reactions" in the Plasma Model <https://chombo-discharge.github.io/chombo-discharge/Applications/CdrPlasmaModel.html?highlight=reaction#specifying-reactions>`_. The comparison of the chemical reactions between ``search-value`` and json file is thus a parsed/semantic comparison.

Navigating a json object hierarchy can sometimes involve having to search through several lists down the tree:

.. code-block::

    {
        "parent":{
            "list-level-1":[
                {
                    "field-name-0":"value_0"
                },
                {
                    "field-name-1":"value_1_0",
                    "target-field":"dont-you-change-me!"
                },
                {
                    "field-name-1":"value_1_1",
                    "target-field":"change-me!"  # <----
                },
                {
                    "field-name-2":"value_2"
                },
            ]
        }
    }

In the above contrived example, we want to change the third contained object in the list; i.e. the object that has ``"field-name-1":"value_1_1"``. The required parameter space uri would be:

.. code-block:: python

    "uri": [
        "parent",
        "list-level-1",
        '+["field-name-1"="value_1_1"]',  # this finds the object
        "target-field"  # this is the actual target within the above object
    ]

A deeper hierarchy with two list levels to traverse:

.. code-block::

    {
        "parent":{
            "list-level-1":[
                {
                    "field-name-0":"value_0"
                },
                {
                    "field-name-1":"value_1_0",
                    "target-field":"dont-you-change-me!"
                },
                {
                    "field-name-1":"value_1_1",
                    "target-field":[
                        {
                            "search-field"="some-value",
                            "target2-field":"don-try-to-change-me!"
                        },
                        {
                            "search-field"="search-value",
                            "target2-field":"change-me!"  # <----
                        }
                    ]
                },
                {
                    "field-name-2":"value_2"
                },
            ]
        }
    }

.. code-block::

    "uri": [
        "parent",
        "list-level-1",
        '+["field-name-1"="value_1_1"]',  # find the right object
        "target-field",  # alter this one
        '+["search-field"="search-value"]',  # find the right object
        "target2-field"  # target aquired!
    ]

The corresponding value specification for this parameter in the run_definition should be a single list: ``"values"=[new-value-0, new-value-1, ..., new-value-N]`` contributing a factor *N* to the parameter space size.

Dummy parameters
^^^^^^^^^^^^^^^^
It is possible to pass ``dummy`` parameters as a mechanism to set options for the jobscripts. A dummy parameter doesn't have to specify a target file, only a name and ``values``-field, and optionally the ``database`` field. The parameter doesn't grow the parameter space size but will end up in the generated ``index.json``, ``structure.json`` and ``parameters.json`` files.

Say, if study's jobscript needs a configurable parameter we can use a dummy parameter to pass it:

.. code-block:: python

    db_study = {
        ...
        "parameter_space": {
            ...  # no "K_min" parameter here
        }
    }

    main_study = {
        ...
        "parameter_space": {
            "K_min": {
                "values": [6.0]
                },
        }
    }

    top_object = dict(
            databases=[db_study],
            studies=[main_study]
            )




Writing Jobscripts
==================

*configurator.py* schedules through sbatch the script ``generic_array_job.sh``. This should be added as a ``job_script_dependency``.

.. code-block:: bash
   :caption: generic_array_job.sh

    #!/bin/bash
    # Author André Kapelrud
    # Copyright © 2025 SINTEF Energi AS

    #SBATCH --account=<cluster account>
    #SBATCH --output=R-%x.%A-%a.out
    #SBATCH --error=R-%x.%A-%a.err

    # typical options needed for running on cluster
    # remove leading '#' to use
    ##SBATCH --nodes=4 --ntasks-per-node=128
    ##SBATCH --partition=normal
    ##SBATCH --time=0-00:10:00

    # Local slurm testing,
    # add extra '#' to comment out
    #SBATCH --ntasks=5 --cpus-per-task=1
    #SBATCH --time=0-00:25:00
                
    set -o errexit
    set -o nounset

    # example sigma2, module loading code
    if command -v module > /dev/null 2>&1
    then
        module restore system
        module load foss/2023a
        module load HDF5/1.14.0-gompi-2023a  # needed by chombo-discharge
        module load Python/3.11.3-GCCcore-12.3.0  # needed by jobscripts
    fi

    python ./jobscript_symlink  # run python through job-script
    exit $?

.. note::
   This could have been the job-script directly, but routing through an intermediate bash-script made it easier to configure module-loading on sigma2.

The script configures the resource requirements, sets error conditions and loads sigma2 system modules (c.f. `Lmod <https://lmod.readthedocs.io/en/latest/>`_).

Template jobscripts
-------------------

At this stage the work is not done, because alot of of the heavy lifting has to be done by your jobscripts. Regard the *configurator.py* script as setting up the infrastructure. It is now up to you to start meaningful simulations. This section gives some examples on how to accomplish this.

Generic python jobscript example
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A vanilla, quite simple python-based jobscript might look like this:

.. code-block:: python
   :caption: generic_array_job_jobscript.py

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

Database-dependent jobscript examples
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This section contains two example jobscripts.

* One for a database where the simulation (chombo discharge) is rerun under some condition.
* One for a study that needs to extract some dataset from a database and set up sub directories per parameter space run.

The jobscripts depend on two python scripts: ``parse_report.py`` and ``config_util.py`` that needs to be included as ``job_script_dependencies`` in the *run_definition*.

.. warning::
   These are not *ready-to-run*, but illustrates a concept. For specific examples see the actual source code listings of this project.

.. code-block:: python
   :caption: Example database (python) jobscript
   :linenos:

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

        # extract the directory prefix of run directories (default is 'run_', but make no assumptions.
        job_prefix = index_dict['prefix']

        # find the directory corresponding to this array task id
        dpattern = f'^({job_prefix}[0]*{task_id:d})$'  # account for possible leading zeros
        dname = [f for f in os.listdir() if (os.path.isdir(f) and re.match(dpattern, f))][0]

        # step into directory
        log.info(f'chdir: {dname}')
        os.chdir(dname)

        # find chombo-discharge *.inputs file
        input_file = None
        for f in os.listdir():
            if os.path.isfile(f) and f.endswith('.inputs'):
                input_file = f
                break

        if not input_file:
            raise ValueError('missing *.inputs file in run directory')

        # We are now ready to run mpi on our chombo-discharge executable through the program symlink
        # If there are any quirks specific to this invocation that is not taken care of in your *.inputs file, you can add them here:
        
        cmd = f"mpirun program {input_file} Random.seed={task_id:d} SomeNamespace.variable=QuirkSolution"
        log.info(f"cmdstr: '{cmd}'")
        p = subprocess.Popen(cmd, shell=True, executable="/bin/bash")
        while p.poll() is None:
            time.sleep(0.5)
        # propagate nonzero exit code to calling jobscript
        if p.returncode != 0:
            sys.exit(p.returncode)

        # First simulation step done.
        # We are free to do whatever is necessary here. One likely scenario is to parse some results, alter some parameters and rerun the invocation above.

        result_fn = "result-file-name"

        def parse_some_result_file(result_filename):
            """ meaningless stub """
            return None

        data = parse_some_result_file(result_fn)
        log.info("Some description of this step...")

        def calculate_interresting_value(data):
            """ meaningless stub """
            return None  # stub
        iv = calculate_interresting_value(data)

        # If we need to read something from a *.inputs file we can of course do that:
        orig_iv = read_input_float_field(input_file, 'SomeNamespace.interrestingvariable')
        if orig_iv None:
            raise RuntimeError(f"'{input_file}' does not contain 'SomeNamespace.interrestingvariable' field")

        # some decision point
        if orig_iv != iv:
            log.info(f'renaming: {result_fn} -> {result_fn}.0')
            shutil.move(result_fn, f'{result_fn}.0') 

            # You might want to back up other results here.

            # update input file, this mirrors the run_definition file syntax
            handle_combination({
                "interresting_parameter": {  # parameter name
                    "target": input_file,  # file target
                    "uri": "SomeNamespace.interrestingvariable"
                    }
                }, dict(interresting_parameter=iv))

            # rerun the simulation!
            log.info('Rerunning calculations')
            p = subprocess.Popen(cmd, shell=True, executable="/bin/bash")
            while p.poll() is None:
                time.sleep(0.5)
            sys.exit(p.returncode)

Study (database-dependent) jobscript example
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This is a rather long example where we traverse the database directories to find relevant data and then set up detailed simulations to use that data. This can be a single simulation, or a complex-subhierarchy of simulations. The last part is only pseudo-code, so the reader is adviced to check out some of the checked in example studies in the main repository.

.. code-block:: python
   :linenos:

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

        S_ENV = 'SLURM_ARRAY_TASK_ID'
        if S_ENV not in os.environ:
            raise RuntimeError(f'${S_ENV} not found in os.environ[]. Run this'
                               ' script through sbatch --array=... !!')
        task_id = int(os.environ['SLURM_ARRAY_TASK_ID'])
        log.info(f'found task id: {task_id}')

        with open('structure.json') as structure_file:
            structure = json.load(structure_file)

        # extract the directory prefix of run directories (default is 'run_', but make no assumptions.
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

        # get access to structure of dependent database through symlink
        with open('../inception_stepper/structure.json') as db_structure_file:
            db_structure = json.load(db_structure_file)

        # determine order of parameters in database (might differ from the order in this study)
        if 'space_order' not in db_structure:
            raise ValueError("missing field 'space_order' in database 'inception_stepper'")
        db_param_order = db_structure['space_order']

        # load this run's parameters (radius, pressure, etc.)
        with open('parameters.json') as param_file:
            parameters = json.load(param_file)

        # we can add run-time checks:
        if 'geometry_radius' not in parameters:
            raise RuntimeError("'geometry_radius' is missing from 'parameters.json'")
       
        # put the parameters in the same order as the database index needs them
        db_search_index = []
        for db_param in db_param_order:
            db_search_index.append(parameters[db_param])

        # Now, we need to locate the corresponding data in the 'database':
        with open('../inception_stepper/index.json') as db_index_file:
            db_index = json.load(db_index_file)

        # linear search through index, which is a dictionary.
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

        # we have the index, now locate the correct subdirectory:
        db_run_path = Path('../inception_stepper')
        if 'prefix' in db_index:
            db_run_path /= db_index['prefix'] + str(index)
        else:
            db_run_path /= DEFAULT_OUTPUT_DIR_PREFIX + str(index)


        def parse_and_get_interresting_data(filename):
            """ stub """
            return None

        data = parse_and_get_interresting_data(db_run_path / '<some-database-result-file>')

        # Maybe we need to do some selective picking of data based on a dummy-parameter?
        # here we can for easily check a 'dummy' parameter
        if 'dummy-parameter' in parameters:
            data = some_filter_action(parameters['dummy-parameter']  #do something meaningful

        #----------------------------------------------------------------------------
        # At this point we can do whatever we like with the data.

        # Maybe the database study gave an estimate of a parameter and we just
        # want to write that parameter to an *.inputs file or *.json file and run
        # a detailed simulation.
        # If so, use the handle_combination() function to write the data and
        # launch the job using mpirun. See database example.

        # If on the other hand, the database produces e.g. a voltage list and some
        # other associated input data, then we need to create a sub-file
        # hierarchy in the run-directory and submit those simulation jobs to slurm.

        # We utilize helper functions from the configurator to alleviate the burden.

        # We will use the generic_array_job_jobscript.py script at the leaf directory level.
        #----------------------------------------------------------------------------

        # let us enumerate the interresting data, assuming some known structure:
        #   data[i] corresponds to the (new) parameters ["voltage", "some-other-parameter"]
        enum_table = list(enumerate(data))

        output_prefix = "voltage_"

        # first we have to create an index for the sub-directories:
        
        # guard for reposting of the job
        MAX_BACKUPS = 10
        index_path = Path('index.json')
        backup_file(index_path, max_backups=MAX_BACKUPS)

        # write voltage index
        with open(index_path, 'w') as voltage_index_file:
            json.dump(dict(
                key=["voltage", "some-other-parameter"],
                prefix=output_prefix,
                index={i: item for i, item in enum_table}
                ),
                      voltage_index_file, indent=4)

        # recreate the generic job-script symlink, so that the actual .sh jobscript work:
        if not os.path.islink('jobscript_symlink'):
            os.symlink('generic_array_job_jobscript.py', 'jobscript_symlink')

        # create run directories, copy files, set voltage and parameters, etc.
        for i, row in enum_table:
            voltage_dir = Path(f'{output_prefix}{i:d}')
            # don't delete old invocations
            backup_dir(voltage_dir, max_backups=MAX_BACKUPS)
            os.makedirs(voltage_dir, exist_ok=False)

            # further symlink program executable to this directory's program-symlink
            link_path = voltage_dir / 'program'
            if not link_path.is_symlink():
                os.symlink(Path('../program'), link_path)

            # grab original file names from structure
            required_files = [Path(f).name for f in structure['required_files']]
            copy_files(log, required_files, voltage_dir)

            # reuse the combination writing code from the configurator / config_util, by
            # building a fake combination and parameter space:
            # populate values
            comb_dict = dict(
                    voltage=row[0],
                    some_other_parameter=row[1]
                    )
            pspace = {
                    "voltage": {
                        "target": voltage_dir/input_file,
                        "uri": "SomeNamespace.potential",
                        },
                    "some_other_parameter": {
                        "target": voltage_dir/'chemistry.json',
                        'uri': [ ... ]  # some very complex JSON traversing uri
                        },
                    }
            handle_combination(pspace, comb_dict)

        # all voltage_* directories are now ready, and we can post a (new!) slurm array job:
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
                    # backups for previously posted runs:
                    backup_file(array_job_id_path, max_backups=MAX_BACKUPS)

                    # write array index file
                    with open(array_job_id_path, 'w') as job_id_file:
                        job_id_file.write(job_id)
                    log.info(f"Submitted array job (for '{structure['identifier']}" +
                             f"_voltage' combination set). [slurm job id = {job_id}]")

            if p.poll() is not None:
                break

Prerequisites
*************
.. toctree::
   :maxdepth: 3
   :caption: Prerequisites
   :hidden:

* Python >= 3.13.0
    
    These additional modules are required:

    * numpy

* Slurm, either local service/cluster or on a larger cluster
* Recent version of python


Example local installation of slurm (debian)
============================================

This section details an example installation and configuration of slurm on debian (either native or through WSL) for local testing. Here the slurm controller, `slurmctld`, will run on the same host as the compute node itself.

* Install required software (listed in order we configure it)

    .. code-block:: bash

       $ sudo apt install munge slurmctld slurmd slurm-client

   Munge is used for key authentication between host controller and compute nodes (here the same machine).

* Configure slurm ``/etc/slurm/slurm.conf``, c.f. `Slurm Quickstart <https://slurm.schedmd.com/quickstart_admin.html#quick_start>`_

    .. important::

        If running in WSL, make sure that the `memory` setting (c.f. `wsl-config <https://learn.microsoft.com/en-us/windows/wsl/wsl-config>`_) in the per-distribution `/etc/wsl.conf` or the global `%homepath%\\.wslconfig` is set high enough — It should at least match the memory configuration in your slurm.conf with an additional margin for the system itself.

* Fix certain non-existing directories (and permissions), log files, or launching slurmctld will fail:

    .. code-block:: bash
       :caption: fix slurmd/slurmctld directory permissions

        # fix log directories and permissions
        sudo mkdir -p /var/log/slurm
        sudo mkdir -p /var/spool/slurmctld
        sudo mkdir -p /var/spool/slurmd
        sudo chown -R slurm:slurm /var/log/slurm /var/spool/slurmctld /var/spool/slurmd

        # make sure that the log exists and has proper permissions
        sudo touch /var/log/slurmctld.log
        sudo chown slurm:slurm /var/log/slurmctld.log
* Start slurmctld:
    
    .. code-block:: bash
        
        $ sudo systemctl start slurmctld
        $ sudo systemctl status slurmctld

    Slurmctld should be running, we can now start the slurm daemon

    .. code-block:: bash
        
        $ sudo systemctl start slurmd
        $ sudo systemctl status slurmd

* Verify node status as seen from the controller. Typical output from a simple setup:

    .. code-block:: bash
        :caption: slurm.conf - excerpt

         ...
        NodeName=my-hostname CPUs=20 RealMemory=15000 State=UNKNOWN
        PartitionName=debug Nodes=ALL Default=YES MaxTime=INFINITE State=UP

    should result in the status info from the controller

    .. code-block:: bash

        $ sinfo
        PARTITION AVAIL  TIMELIMIT  NODES  STATE NODELIST
        debug*       up   infinite      1   idle my-hostname

    It should now be possible to submit jobs using e.g. the slurm `sbatch` command.

* (optional) enable services to launch at boot:

    .. code-block:: bash

        $ sudo systemctl enable slurmctld.service
        $ sudo systemctl enable slurmd.service

