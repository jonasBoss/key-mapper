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


import evdev
from evdev.ecodes import EV_KEY

from keymapper.utils import DEV_NAME, is_keyboard_code
from keymapper.logger import logger


class UInput(evdev.UInput):
    
    def __init__(self, *args, **kwargs):
        super().__init__( *args, **kwargs)
    
    def can_emit(self, event):
        """ceck it a event can be emitted by the uinput
        
        Wrong events might be injected if the group mappings are wrong
        """
        # TODO check for event value especially for EV_ABS
        try:
            return event[1] in self.capabilities().get(event[0], [])
        except evdev.uinput.UInputError:
            logger.debug("uinput for %s is not available", self.name)
            self.device = self._find_device()
            return event[0] in self.capabilities().keys() and event[1] in self.capabilities()[event[0]]
    
    
class GlobalUInputs:
    """Manages all uinputs that are shared between all injection processes."""
    def __init__(self):
        self.devices = {}

    def prepare(self):
        """Generate uinputs.

        This has to be done in the main process before injections start.
        """
        # Using all EV_KEY codes broke it in one installation, the use case for
        # keyboard_output (see docstring of Context) only requires KEY_* codes here
        # anyway and no BTN_* code.
        # Furthermore, python-evdev modifies the ecodes.keys list to make it usable,
        # only use KEY_* codes that are in ecodes.keys therefore.
        keys = list(evdev.ecodes.KEY.keys() & evdev.ecodes.keys.keys())
        self.devices["keyboard"] = UInput(
            name="key-mapper keyboard",
            phys=DEV_NAME,
            events={evdev.ecodes.EV_KEY: keys},
        )

    def get_uinput(self, name):
        """UInput with name

        Or None if there is no uinput with this name.

        Parameters
        ----------
        name : uniqe name of the uinput device
        """
        if name in self.devices.keys():
            return self.devices[name]

        return None


global_uinputs = GlobalUInputs()
