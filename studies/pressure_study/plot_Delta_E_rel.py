
import numpy as np
import matplotlib.pyplot as plt
import re
import json
import sys

if __name__ == '__main__':
    
    num_steps = 1001
    E_rel = np.zeros(num_steps)
    t = np.zeros(num_steps)
    ts = None

    with open('index.json') as index_file:
        index = json.load(index_file)

    max_i = -1
    for key,value in index['index'].items():
        if int(key) > max_i:
            max_i = int(key)
    
    prefix = 'pout'
    if len(sys.argv) == 2:
        prefix = sys.argv[1]

    for i in range(0, max_i+1):
        with open(f'{prefix}{i:d}.0') as pout:
            for line in pout:
                if line.startswith("Driver::Time step report -- Time step #"):
                    ls = line.split("#")
                    ts = int(ls[1].strip())
        
                m = re.match(r'Time\s*=\s(?P<time>[-+]?([0-9]*\.[0-9]+|[0-9]+)([eE][-+]?[0-9]+)?)', line.strip())
                if m and ts:
                    t[ts] = float(m.groupdict()['time'])

                m = re.match(r'Delta E\(rel\)\s*=\s(?P<E_rel>[-+]?([0-9]*\.[0-9]+|[0-9]+)([eE][-+]?[0-9]+)?)\s\(%\)', line.strip())
                if m and ts:
                    E_rel[ts] = float(m.groupdict()['E_rel'])

        f = plt.figure(figsize=[8,4])
        plt.plot(t[:ts]*1e9, E_rel[:ts])
        plt.ylabel(r'$\Delta E_\text{rel}$')
        plt.xlabel('$t$ [ns]')

        meta = index['index'][str(i)]
        plt.title('$K={:.1f}, U={}\\,\\mathrm{{V}}$'.format(
            meta[1], 100*round(meta[0]/100)))
        plt.savefig(f'plt_{i:d}.png')
        #plt.show()

