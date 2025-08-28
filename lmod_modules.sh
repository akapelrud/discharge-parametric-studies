#!/bin/bash

module restore system

# load modules, consistent with GCCcore-12.3.0:
module load foss/2023a
module load HDF5/1.14.0-gompi-2023a
module load Python/3.11.3-GCCcore-12.3.0
module load SciPy-bundle/2023.07-gfbf-2023a  # i.e. numpy and friends
module load Visit/3.4.1-foss-2023a
