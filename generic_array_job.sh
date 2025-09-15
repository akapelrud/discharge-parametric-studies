#!/bin/bash
# Author André Kapelrud
# Copyright © 2025 SINTEF Energi AS

#SBATCH --account=nn12041k
##SBATCH --nodes=4 --ntasks-per-node=128
#SBATCH --ntasks=5 --cpus-per-task=1
#SBATCH --time=0-00:10:00
##SBATCH --partition=normal
#SBATCH --time=0-00:25:00
#SBATCH --output=R-%x.%A-%a.out
#SBATCH --error=R-%x.%A-%a.err
            
set -o errexit
set -o nounset

if command -v module > /dev/null 2>&1
then
    module restore system
    module load foss/2023a
    module load HDF5/1.14.0-gompi-2023a
    module load Python/3.11.3-GCCcore-12.3.0
fi

python ./jobscript_symlink
exit $?

