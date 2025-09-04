#!/usr/bin/env python
"""
Author André Kapelrud
Copyright © 2025 SINTEF Energi AS
"""

import json
import numpy as np

inception_stepper = {
        'identifier': 'inception_stepper',
        'job_script': 'discharge_inception_jobscript.py',
        'program': 'InceptionStepper/program{DIMENSIONALITY}d.Linux.64.mpic++.gfortran.OPTHIGH.MPI.ex',
        'output_directory': 'is_db',
        'job_script_dependencies': [
            'generic_array_job.sh',
            'parse_report.py',
            'config_util.py',
            'json_requirement.py'
            ],
        'required_files': [
            'master.inputs',
            'InceptionStepper/transport_data.txt'
            ],
        'parameter_space': {
            "pressure": {
                "target": "master.inputs",
                "uri": "DischargeInception.pressure"
                },
            "geometry_radius": {
                "target": "master.inputs",
                "uri": "Rod.radius",
                },
            'K_max': {
                "target": "master.inputs",
                "uri": "DischargeInceptionStepper.limit_max_K"
                }
            }
        }

plasma_study_1 = {
        'identifier': 'photoion',
        'program': 'Plasma/program{DIMENSIONALITY}d.Linux.64.mpic++.gfortran.OPTHIGH.MPI.ex',
        'job_script': 'plasma_jobscript.py',
        'job_script_dependencies': [
            'generic_array_job.sh',
            'parse_report.py',
            'config_util.py',
            'json_requirement.py',
            ],
        'required_files': [
            'master.inputs',
            'Plasma/chemistry.json',
            'Plasma/detachment_rate.dat',
            'Plasma/electron_transport_data.dat',
            'generic_array_job.sh',  # used at voltage step level
            'generic_array_job_jobscript.py'  # used at voltage step level
            ],
        'output_directory': 'study0',
        'output_dir_prefix': 'run_',
        'parameter_space': {
            "geometry_radius": {
                "database": "inception_stepper",  # database dependency
                "target": "master.inputs",
                "uri": "Rod.radius",
                "values": [1e-3] #, 2e-3, 3e-3]
                },
            "pressure": {
                "database": "inception_stepper",  # database dependency
                "target": "chemistry.json",
                "uri": ["gas", "law", "my_ideal_gas", "pressure"],
                "values": [1e5]  # np.arange(1e5, 11e5, 10e5).tolist()
                },
            "K_min": { "values": [8] }, # needed by jobscript, written to parameters.json for each run
            "K_max": {
                "database": "inception_stepper",
                "values": [17.0]
                },
            "plasma_polarity": { "values": ["positive"] },  # used by jobscript
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
        studies=[plasma_study_1]
        )

if __name__ == '__main__':
    with open('runs.json', 'w') as f:
        json.dump(top_object, f, indent=4)
