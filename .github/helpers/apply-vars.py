#!/usr/bin/env python3

#
# NOTICE: This file is synchronized on-demand by synchronize.yaml job from a shared library directory
#

import os.path
import sys
import glob


def load_vars(path: str) -> dict:
    parsed_vars = {}

    with open(path, 'r') as f:
        content = f.read().split("\n")

        for line in content:
            split = line.split("=", 1)

            if len(split) < 2:
                continue

            name = split[0]
            value = split[1]

            parsed_vars[name] = value

    return parsed_vars


def replace_vars(directory_path: str, variables: dict):
    for file in glob.iglob(directory_path + "/**/*", recursive=True):
        if not os.path.isfile(file):
            continue

        print(f' >> Processing {file}')

        with open(file, "r") as r:
            content = r.read()

        with open(file, "w") as w:
            for name, value in variables.items():
                content = content.replace("{{" + name + "}}", value)

            w.write(content)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Please specify a directory')
        sys.exit(1)

    replace_vars(sys.argv[1], load_vars(".github/helpers/ci-vars.env"))
