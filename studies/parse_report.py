#!/usr/bin/env python
"""
Author André Kapelrud
Copyright © 2025 SINTEF Energi AS
"""

from itertools import groupby, tee
import sys


def parse_report_file(filename: str, interresting: list[str] = None) -> \
        tuple[list[str], list[tuple[float, list[float]]]]:
    """ Parse an inception stepper report file containing e.g. optimal starting
    positions for electrons
    """
    with open(filename) as f:
        previous_lines = ['', '']
        header = None

        columns = []  # header fields
        dimensionality = 0  # dimensionality of vectors
        A = []

        for line in f:
            if line[0] == '#':
                previous_lines[1] = previous_lines[0]
                previous_lines[0] = line
                continue

            if not header:
                header = previous_lines[1]

                # use the 1st data row to get field positions and
                # dimensionality (assuming this is consistent for the header as
                # well
                field_positions = []
                field_dims = []
                vector_started = False
                for k, g in groupby(enumerate(line),
                                    lambda x: not x[1].isspace()):
                    if k:
                        pos, first_item = next(g)
                        field = first_item + ''.join([x for _, x in g])

                        if not vector_started:
                            dim = 1
                        if field[-1] == ',':
                            dim += 1
                            if field[0] != '(':
                                continue
                            vector_started = True
                        elif field[-1] == ')':
                            if not dimensionality:
                                dimensionality = dim
                            field_dims.append(dim)
                            vector_started = False
                            continue

                        if dim == 1:
                            field_dims.append(dim)
                        field_positions.append(pos)

                # rearrange to header ranges
                field_positions.append(-1)
                a, b = tee(field_positions)
                next(b, None)

                for pos_pair in zip(a, b):
                    field = header[pos_pair[0]:pos_pair[1]].strip()
                    if field[0] == '#':
                        field = field[1:].lstrip()
                    columns.append(field)

                if interresting is None:
                    interresting = columns

            def take_vec(iterator, d):
                assert d > 1
                vec = []
                for i in range(d):
                    if i == 0:  # discard leading '(' and trailing ','
                        vec.append(float(next(iterator)[1:-1]))
                    else:  # discard trailing ',' and ')'
                        vec.append(float(next(iterator)[0:-1]))
                return tuple(vec)

            # parse data rows as normal
            res = []
            fields = line.split()
            it = iter(fields)
            for col, d in zip(columns, field_dims):
                if col in interresting:
                    if d == 1:
                        res.append(float(next(it)))
                    elif d > 1:
                        res.append(take_vec(it, d))
                else:
                    for i in range(d):  # skip ahead
                        next(it)
            A.append(tuple(res))
        return ([col for col in columns if col in interresting], A)


if __name__ == '__main__':

    filename = 'report.txt'
    if len(sys.argv) > 1:
        filename = sys.argv[1]
    res = parse_report_file(filename,
                            ['+/- Voltage', 'Max K(+)', 'Max K(-)',
                             'Pos. max K(+)', 'Pos. max K(-)'])
    print(res)
