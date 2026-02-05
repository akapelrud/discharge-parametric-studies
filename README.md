# discharge-parametric-studies
A collection of batch and slurm scripts for running multilevel chombo-discharge studies over wide parameter spaces

## Usage
The `configurator.py` script can be used to set up directory structures for wide parametric sweeps over chombo-discharge based studies.

```bash
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

```

# Compilation

To make both programs (inception-stepper program and itokmc-based program), run
```
$ make -j4
```
where `-j<num>` is the number of cores to use for the compilation. Add `-s` flag to make the compilation silent. This will enter the relevant cases-subfolder and build executables.

