#!/bin/bash

#SBATCH --account=nn12041k
##SBATCH --nodes=4 --ntasks-per-node=128
#SBATCH --time=0-00:10:00
##SBATCH --partition=normal
#SBATCH --time=0-00:10:00
#SBATCH --output=R-%x.%A-%a.out
#SBATCH --error=R-%x.%A-%a.err
            
set -o errexit
set -o nounset

if command -v module > /dev/null 2>&1
then
    module restore system
    module load foss/2023a
    module load HDF5/1.14.0-gompi-2023a
    module load Python/3.12.3-GCCcore-13.3.0
fi

# run jobscript through expected symbolic link
python ./jobscript_symlink

