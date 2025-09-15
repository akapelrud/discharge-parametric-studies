#!/bin/bash

# Author André Kapelrud
# Copyright © 2025 SINTEF Energi AS

for i in run_*/; do
	cd $i
	echo "parameters.json:"
	cat parameters.json
	echo ""
	python ../gather.py
	echo -e "\n===================================\n"
	cd ..
done
