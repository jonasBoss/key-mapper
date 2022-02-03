#!/usr/bin/python3
# -*- coding: utf-8 -*-
# input-remapper - GUI for device specific keyboard mappings
# Copyright (C) 2022 sezanzeb <proxima@sezanzeb.de>
#
# This file is part of input-remapper.
#
# input-remapper is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# input-remapper is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with input-remapper.  If not, see <https://www.gnu.org/licenses/>.

from typing import Tuple, Dict, Optional

from inputremapper import exceptions
from inputremapper.configs.mapping import Mapping
from inputremapper.event_combination import EventCombination
from inputremapper.injection.mapping_handlers.mapping_handler import MappingHandler, ContextProtocol, HandlerEnums
from inputremapper.logger import logger
from inputremapper.input_event import InputEvent
from inputremapper.injection.global_uinputs import global_uinputs


class KeyHandler(MappingHandler):
    """injects the target key if notified"""
    _active: bool
    _maps_to: Tuple[int, int]

    def __init__(
            self,
            combination: EventCombination,
            mapping: Mapping,
            context: ContextProtocol = None,
    ):
        super().__init__(combination, mapping)
        self._maps_to = mapping.get_output_type_code()
        self._active = False
        assert self._maps_to is not None

    def __str__(self):
        return f"KeyHandler <{id(self)}>:"

    def __repr__(self):
        return self.__str__()

    @property
    def child(self):  # used for logging
        return f"maps to: {self._maps_to} on {self.mapping.target_uinput}"

    def notify(self, event: InputEvent, *_, **__) -> bool:
        """inject event.value to the target key"""

        event_tuple = (*self._maps_to, event.value)
        try:
            global_uinputs.write(event_tuple, self.mapping.target_uinput)
            logger.debug_key(event_tuple, "sending to %s", self.mapping.target_uinput)
            self._active = bool(event.value)
            return True
        except exceptions.Error:
            return False

    def needs_wrapping(self) -> bool:
        return True

    def wrap_with(self) -> Dict[EventCombination, HandlerEnums]:
        return {self.input_events: HandlerEnums.combination}

