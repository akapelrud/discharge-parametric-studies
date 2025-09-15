#!/usr/bin/env python
"""
Author André Kapelrud
Copyright © 2025 SINTEF Energi AS
"""

from collections import deque
import json
import re

if __name__ == '__main__':
    
    with open('index.json') as indexfile:
        index = json.load(indexfile)

        for key,value in index['index'].items():
            print(f"i={key} :: U={value[0]} V, K={value[1]}")

            tail = None
            with open(f'voltage_{int(key):d}/pout.0') as pout:
                tail = deque(pout, 50) 


            inception = False
            for line in tail:
                if line.startswith("Driver::Time step report -- Time step #"):
                    ls = line.split("#")
                    print(f"Time step {ls[1]}")

                m = re.match(r'Time\s*=\s(?P<time>[-+]?([0-9]*\.[0-9]+|[0-9]+)([eE][-+]?[0-9]+)?)', line.strip())
                if m:
                    t = float(m.groupdict()['time'])
                    print(line.strip())
                    continue

                m = re.match(r'dt\s*=\s(?P<dt>[-+]?([0-9]*\.[0-9]+|[0-9]+)([eE][-+]?[0-9]+)?)', line.strip())
                if m:
                    t = float(m.groupdict()['dt'])
                    print(line.strip())
                    continue

                if line.find("abort") > 0:
                    print(line, end="")
                    if line.startswith("ItoKMCBackgroundEvaluator -- abort because field changed by more than specified threshold"):
                        inception = True

                if line.startswith("ItoKMCGodunovStepper::advanceEulerMaruyama - Poisson solve did not converge"):
                    print(line, end="")
                #print(line, end="")
            if inception:
                print('Inception likely occurred')
            print('-------------------------------')
