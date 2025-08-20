#!/usr/bin/env python

import json
import logging
import fileinput
import re
import shutil
import sys
from pathlib import Path

from json_requirement import match_requirement, match_reaction

DEFAULT_OUTPUT_DIR_PREFIX = 'run_'


def parse_commented_json_to_dict(filepath):
    """ Reads filepath line by line and strips all C++ style block (//) comments. Parse
    using json module and return contents as a dict.
    """
    json_content = []
    with open(filepath) as json_file:
        for line in json_file:
            json_content.append(line.partition('//')[0])  # strip comments
    return json.loads(''.join(json_content))


def set_nested_value(d, keys: list[str], value):
    """ Set the value for a nested dictionary hierarchy using a list of keys as the
    depth address
    """
    log = logging.getLogger(sys.argv[0])

    for key in keys[:-1]:
        if isinstance(d, list):  # here we have to search
            if not (key.startswith('+[') or key.startswith('*[')):
                raise RuntimeError('no requirement found for matching to list '
                                   f'element for key: {key}')
            md = match_requirement(key)
            if not md:
                raise ValueError(f'match requirement: \"{key}\" is malformed')

            found_requirement = False
            for element in d:
                if not isinstance(element, dict):
                    log.warning('found non-dict/object in list when trying to match '
                                'requirement. Skipping element.')
                    continue

                if not md['field'] in element:
                    continue

                match md['type']:
                    case 'chem_react':
                        found_requirement = match_reaction(
                                md['value'], element[md['field']])
                    case _:
                        if md['value'] is None:
                            found_requirement = True
                        else:
                            found_requirement = element[md['field']] == md['value']

                if found_requirement:
                    d = element
                    break

            if not found_requirement:
                if key[0] == '+':  # non-optional requirement
                    raise RuntimeError('missing list element has requirement')

                d.append({md['field']: md['value']})
                d = d[-1]

        else:
            d = d.setdefault(key, {})  # Create nested dicts if they don't exist
    d[keys[-1]] = value  # set the leaf node value


def expand_uri(uri, disparate=False, level=0):
    res = []
    if isinstance(uri, list):
        for uri_elem in uri:
            if disparate:
                disparate_exp_res = expand_uri(uri_elem, False, level)
                if isinstance(disparate_exp_res[0], list):
                    for r in disparate_exp_res:
                        res.append(r)
                else:
                    res.append(disparate_exp_res)
            else:
                parent_is_list = len(res) > 0 and isinstance(res[0], list)
                if not isinstance(uri_elem, list):
                    if parent_is_list:
                        for i in range(len(res)):
                            res[i].append(uri_elem)
                    else:
                        res.append(uri_elem)
                else:
                    # check for nested lists
                    if level > 0 and isinstance(uri_elem, list):
                        for sub in uri_elem:
                            if isinstance(sub, list):
                                raise ValueError("Nested lists are not allowed beyond "
                                                 "the 3rd level")
                    sub_tree = expand_uri(uri_elem, level=level+1)
                    tree_res = []
                    for tree in sub_tree:
                        if parent_is_list:
                            for i in range(len(res)):
                                tree_res.append([*res[i], tree])
                        else:
                            tree_res.append([*res, tree])
                    res = tree_res
    else:
        res.append(uri)

    if level == 0 and len(res) and not isinstance(res[0], list):
        res = [res]
    return res


def handle_json_combination(json_content, key, pspace, comb_dict):
    """ Write key value from comb_dict to the appropriate json uri
    """
    disparate = 'disparate' in pspace[key] and pspace[key]['disparate']
    expanded_uri = expand_uri(pspace[key]['uri'], disparate=disparate)
    dims = len(expanded_uri)

    if dims > 1:
        if not isinstance(comb_dict[key], list):
            raise ValueError(f"requirement '{pspace[key]['uri']}' has dims>1 "
                             "but value is a scalar")
        elif dims != len(comb_dict[key]):
            raise ValueError("requirement uri has different dimensionality "
                             "than value field")
    for i, uri in enumerate(expanded_uri):
        set_nested_value(json_content, uri,
                         comb_dict[key] if dims == 1 else comb_dict[key][i])


def handle_input_combination(input_file, key, pspace, comb_dict):
    """
    warning: writes directly to input_file, search and replace mode
    """
    if 'uri' not in pspace[key]:
        raise ValueError(f'No uri for input requirement: {key}')
    if not isinstance(pspace[key]['uri'], str):
        raise ValueError(f'input requirement can only be a scalar string: {key}')
    if pspace[key]['uri'] == "":
        raise ValueError(f'empty uri string for: {key}')
    uri = pspace[key]['uri']

    def format_value(value):
        if isinstance(value, list):
            try:
                float(value[0])
                isfloat = True
            except ValueError:
                isfloat = False

            if isfloat:
                newvalue = " ".join([f'{v:g}' for v in value])
            else:
                newvalue = " ".join(value)
        else:
            newvalue = value
        return newvalue

    found_line = False
    for line in fileinput.input(input_file, inplace=True):  # print() writes to file
        if not found_line and line.startswith(pspace[key]['uri']):
            content = line
            commentpos = content.find('#')
            comment = ""
            if commentpos != -1:
                comment = line[commentpos+1:].rstrip()
                content = line[:commentpos]

            eq_pos = content.find('=')
            if eq_pos == -1:
                continue
            address = content[:eq_pos]
            value = content[eq_pos+1:]
            value_whitespace = re.match(r'\s*', value).group()

            if address.strip() == uri:
                found_line = True
                newline = f'{address}={value_whitespace}{format_value(comb_dict[key])}'
                newline_len = len(newline)

                # add comment
                comment_begin = ' # [script-altered]'
                if commentpos != -1:
                    if newline_len+1 <= commentpos:
                        newline += " "*(commentpos-newline_len-1)
                newline += comment_begin + comment
                line = newline + '\n'
        sys.stdout.write(line)

    if not found_line:
        with open(input_file, 'a') as in_file:
            in_file.write(f"\n{pspace[key]['uri']} = {format_value(comb_dict[key])}"
                          " #[script-added]")


def handle_combination(pspace, comb_dict):
    log = logging.getLogger(sys.argv[0])

    json_cache = {}
    for key in comb_dict.keys():
        target = Path(pspace[key]['target'])

        log.debug(f"key: {key}, target: {target}")

        match target.suffix:
            case '.json':
                json_content = None
                if target in json_cache:
                    json_content = json_cache[target]
                else:
                    json_content = parse_commented_json_to_dict(target)
                    json_cache[target] = json_content
                handle_json_combination(json_content, key, pspace, comb_dict)
            case '.inputs':
                handle_input_combination(target, key, pspace, comb_dict)
            case _:
                continue

    # write back all modified json caches
    for key, value in json_cache.items():
        with open(key, 'w') as json_file:
            json.dump(value, json_file, indent=4)


def copy_files(log, required_files, destination):
    """ Copy the required files to the destination
    """
    for file in required_files:
        shutil.copy(file, destination, follow_symlinks=True)
        log.debug(f'copying in file: {file}')


def get_output_prefix(obj):
    output_dir_prefix = DEFAULT_OUTPUT_DIR_PREFIX
    if 'output_dir_prefix' in obj:
        odp = obj['output_dir_prefix']
        if not isinstance(odp, str):
            raise ValueError("'output_dir_prefix' in structure: " +
                             f"'{odp}' is not a string'")
        output_dir_prefix = obj['output_dir_prefix']
    return output_dir_prefix
