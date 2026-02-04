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

Introduction
************
.. toctree::
   :maxdepth: 3
   :caption: Introduction
   :hidden:

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

Each database or study step relies on running a (chombo-discharge) executable repeatedly, and often in parallel, over a defined parameter set. Ex.: if a parameter *pressure* should be varied over 5 different values, and another parameter *radius* should be varied over 3 different values, the parameter space would require 15 distinct runs.

Now, the preliminary database study might only depend on the *pressure*, while the whole main study depends on both parameters. This would result in 5 jobs (submitted as parallel array job to slurm) for the database study, **followed** by 15 jobs (parallel, and depending on the success of the first database's array job) for the main study.


Run Definition
==============


A database/study will have these configurable fields:

* ``identifier``
* ``program``, executable to run
* ``output_directory``, relative to the cmdline output directory, i.e.  `--output-dir`
* ``output_dir_prefix``
* ``job-script``,
* ``job_script_dependencies``
* ``required_files``
* ``parameter_space``, a dictionary of parameters to vary

The difference between ``job_script_dependencies`` and ``required_files`` is that the ``required_files`` will be copied into the bottom-level directory where the program is run from, i.e. into every specific *run* directory for every invocation over the parameter space.

- ``required_files`` is typically used for `*.inputs` chombo-discharge files, physical/chemical input files like `*.json` files, or other plain data files. Sometimes extra python modules or bash-scripts might be needed at the run-level, so use this field to copy those dependencies in.
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
        'output_dir_prefix': 'run_',
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

The example above has a more realistic structure. How the parameter spaces are defined can be found in a later section. The resulting file hierarchy from this looks like

.. code-block:: bash

    
    $ ls -R output_directory
    .:
    is_db  study0

    ./is_db
    jobscript_symlink  plasma_jobscript.py  generic_array_job.sh
    


For each database/study there are certain index files that created, such that one can backtrack and find the run index from a given parameter space configuration. This is important as the second-level studies might have to traverse the database result hierarchies to retrieve and parse those results before launching their own slurm jobs. Python utility functions are provided to manipulate configuration files on-the-fly in this intermediate step. More on this later.

The `configurator.py` script contains helper code to in-place manipulate both `.*inputs` files (normally used to specify chombo-discharge parameters), as well as generic structured `.json` files (e.g. used by chombo-discharge or physical/chemical data input.

The actual parameter values are only specified for the top study definition. The database only specifies where changes are to be made for a given value.
Parameter Space
---------------

A parameter space (key: `parameter_space`) is defined as:

.. code-block:: python

    'parameter_space' = {
        'target': <file-name>,
        'uri': <file-specific-URI>
    }


Prerequisites
*************
.. toctree::
   :maxdepth: 3
   :caption: Prerequisites
   :hidden:

* Python >= 3.13.0
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

