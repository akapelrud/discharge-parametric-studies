#!/usr/bin/env python

import json
import numpy as np

inception_stepper = {
        'identifier': 'inception_stepper',  # unique
        'job_script': 'inception_stepper_jobscript.py',
        'program': 'InceptionStepper/program{DIMENSIONALITY}d.Linux.64.mpic++.gfortran.OPTHIGH.MPI.ex',
        'result_files': ['report.txt'],
        'output_directory': 'is_db',
        'required_files': [
            'master.inputs',
            'transport_data.txt',
            'parse_report.py'
            ],
        'parameter_space': {
            "pressure": {
                "target": "master.inputs",
                "uri": "InceptionStepper.pressure"
                },
            "geometry_radius" : {
                "target" : "master.inputs",
                "uri" : "Vessel.rod_radius",
                }
            }
        }

plasma_study_1 = {
        'job_script': 'plasma_jobscript.py',
        'identifier': 'some_id',
        'program': 'Plasma/program{DIMENSIONALITY}d.Linux.64.mpic++.gfortran.OPTHIGH.MPI.ex',
        'required_files': [
            'master.inputs',
            'chemistry.json',
            'bolsig_air.dat'
            ],
        'output_directory': 'study0',
        'output_dir_prefix':'run_',
        'parameter_space': {
            "pressure" : {
                "database": "inception_stepper",  # database dependency
                "target" : "chemistry.json",
                "uri" : ["gas", "law", "my_ideal_gas", "pressure"],
                "values" : list(np.arange(1e5, 11e5, 1e5))
                },
            "geometry_radius" : {
                "database": "inception_stepper",  # database dependency
                "target" : "master.inputs",
                "uri" : "Vessel.rod_radius",
                "values" : [ [0.0, 25e-3] ]
                },
            "photoionization" : {
                "target" : "chemistry.json",
                "uri" : [
                    "photoionization",
                    [
                        '+["reaction"=<chem_react>"Y + (O2) -> e + O2+"]', # non-optional match
                        '*["reaction"=<chem_react>"Y + (O2) -> (null)"]' # optional match (create-if-not-exists)
                        ],
                    "efficiency"
                    ],
                "values" : [[float(v), float(1.0-v)] for v in np.arange(0.0, 1.0, 0.25)]
                },
            }
        }

top_object = dict(
    databases = [inception_stepper],
    studies = [plasma_study_1]
    )

if __name__ == '__main__':
    with open('runs.json', 'w') as f:
        json.dump(top_object, f, indent=4)

