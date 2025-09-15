#!/usr/bin/env python
"""
Author André Kapelrud
Copyright © 2025 SINTEF Energi AS
"""

import re


def match_requirement(suggested: str):
    """Match a field requirement when dealing with a list of objects in json.

    Parameters
    ----------
    suggested : str
        string following the documented requirement format:
            '+["some_field"=<parse_type>"some_value"]'
            '*["some_field"=<parse_type>"some_value"]'
        where the rhs '=<type>"value"' part is optional.
            - This function does not do anything special with the parse_type, field or value
            - For this function there is no difference between *[] and +[], but the
              intention is for the user code to discriminate between optional (*) and
              hard requirement (+).

    Returns
    -------
    dict or None
        req_type: '*' or '+'
        field: 'some_field'
            not None
        type: 'parse_type'
            str or None
        value: 'some_value'
            str or None

    Example
    -------
    Given a 
    [
        {
            'some_field':'value'
        },
        {
            'some_field':'other_value'
        },
        {
            'some_other_field':'third_value'
        }
    ]

    The intention is to be able to specify the first list element with the requirement
    specifier: '+["some_field"]'.
    If a specific field is needed, the value can be matched:
    '+["some_field"="other_value"]

    Notes
    -----

    The type field is optional and can be used to indicate special parsing.:
        type = chem_react
            :: used to indicate that the value should be treated as a
            chombo-discharge reaction equation. c.f. match_reaction function below.

    c.f. https://chombo-discharge.github.io/chombo-discharge/Applications/ItoKMC.html#reaction-specifiers

    """
    pattern = r'^(?P<req_type>\+|\*)\[\s*\"(?P<field>.+?)\"\s*' + \
            r'(?:=\s*(?:<(?P<type>.+?)?>)?\s*\"(?P<value>.+?)\")?' + \
            r'\s*\]$'
    m = re.match(pattern, suggested)
    if not m:
        return None
    return m.groupdict()


def match_reaction(expected, suggested):
    """Match a chemical reaction according to the chombo-discharge specification

    c.f. https://chombo-discharge.github.io/chombo-discharge/Applications/ItoKMC.html#reaction-specifiers

    The order of the reactants on the lhs and rhs are not important.
    Only the set of reactants are compared, not the multiplicity of each species.
    """
    pattern = r'^\s*(.*?)\s*->\s*(.*?)\s*$'

    exp_res = re.match(pattern, expected)
    sug_res = re.match(pattern, suggested)

    if not exp_res:
        raise ValueError('expected reaction is not a valid reaction containing "->"')
    if not sug_res:
        raise ValueError('suggested reaction is not a valid reaction containing "->"')

    def parse_reactants(side):
        parts = re.split(r'\s+\+\s+', side)
        return {part.strip() for part in parts}

    exp_lhs = parse_reactants(exp_res.group(1))
    exp_rhs = parse_reactants(exp_res.group(2))

    sug_lhs = parse_reactants(sug_res.group(1))
    sug_rhs = parse_reactants(sug_res.group(2))

    similar = exp_lhs == sug_lhs and exp_rhs == sug_rhs
    return similar


if __name__ == '__main__':

    m = match_requirement('+["reaction"=<chem_react>"Y + (O2) -> e + O2+"]')

    if m and 'req_type' in m:
        print(f"requirement type: {m['req_type']}")

    # assume this was extracted from a json file:
    from_file = 'Y + (O2) -> e + O2+'

    if m and m['type'] == 'chem_react':
        sim = match_reaction(m['value'], from_file)
        print(f'reaction spec matches file content: \'{m["value"]}\'')
