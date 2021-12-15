#!/usr/bin/python3
# -*- coding: utf-8 -*-
# key-mapper - GUI for device specific keyboard mappings
# Copyright (C) 2021 sezanzeb <proxima@sezanzeb.de>
#
# This file is part of key-mapper.
#
# key-mapper is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# key-mapper is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with key-mapper.  If not, see <https://www.gnu.org/licenses/>.


"""Migration functions"""


import os
import json
import copy

from pathlib import Path
import pkg_resources

from keymapper.logger import logger, VERSION
from keymapper.paths import get_preset_path, mkdir, CONFIG_PATH


def all_presets():
    """All presets for all groups as list"""
    preset_path = Path(get_preset_path())
    presets = []
    for folder in preset_path.iterdir():
        if not folder.is_dir():
            continue

        for preset in folder.iterdir():
            if preset.suffix == ".json":
                presets.append(preset)
    return presets


def config_version():
    """Version string in the config.json as packaging.Version"""
    config_path = os.path.join(CONFIG_PATH, "config.json")
    config = {}

    if not os.path.exists(config_path):
        return pkg_resources.parse_version("0.0.0")

    with open(config_path, "r") as file:
        config = json.load(file)

    if "version" in config.keys():
        return pkg_resources.parse_version(config["version"])

    return pkg_resources.parse_version("0.0.0")


def _config_suffix():
    """append .json suffix to config file"""
    deprecated_path = os.path.join(CONFIG_PATH, "config")
    config_path = os.path.join(CONFIG_PATH, "config.json")
    if os.path.exists(deprecated_path) and not os.path.exists(config_path):
        logger.info('Moving "%s" to "%s"', deprecated_path, config_path)
        os.rename(deprecated_path, config_path)


def _preset_path():
    """Migrate the folder structure from < 0.4.0.

    Move existing presets into the new subfolder "presets"
    """
    new_preset_folder = os.path.join(CONFIG_PATH, "presets")
    if os.path.exists(get_preset_path()) or not os.path.exists(CONFIG_PATH):
        return

    logger.info("Migrating presets from < 0.4.0...")
    groups = os.listdir(CONFIG_PATH)
    mkdir(get_preset_path())
    for group in groups:
        path = os.path.join(CONFIG_PATH, group)
        if os.path.isdir(path):
            target = path.replace(CONFIG_PATH, new_preset_folder)
            logger.info('Moving "%s" to "%s"', path, target)
            os.rename(path, target)

    logger.info("done")


def _mapping_keys():
    """update all preset mappings

    Update all keys in mapping to include value e.g.: "1,5"->"1,5,1"
    """
    if not os.path.exists(get_preset_path()):
        return  # don't execute if there are no presets
    for preset in all_presets():
        preset_dict = {}
        with open(preset, "r") as file:
            preset_dict = json.load(file)
        if "mapping" in preset_dict.keys():
            mapping = copy.deepcopy(preset_dict["mapping"])
            for key in mapping.keys():
                if key.count(",") == 1:
                    preset_dict["mapping"][f"{key},1"] = preset_dict["mapping"].pop(key)

        with open(preset, "w") as file:
            json.dump(preset_dict, file, indent=4)
            file.write("\n")


def _update_version():
    """Write current version string to the config file"""
    config_file = os.path.join(CONFIG_PATH, "config.json")
    if not os.path.exists(config_file):
        return

    logger.info("version in config file to %s", VERSION)
    with open(config_file, "r") as file:
        config = json.load(file)

    config["version"] = VERSION
    with open(config_file, "w") as file:
        json.dump(config, file, indent=4)


def migrate():
    """Migrate config files to the current release"""
    v = config_version()
    if v < pkg_resources.parse_version("0.4.0"):
        _config_suffix()
        _preset_path()

    if v < pkg_resources.parse_version("1.2.2"):
        _mapping_keys()

    # add new migrations here

    if v < pkg_resources.parse_version(VERSION):
        _update_version()
