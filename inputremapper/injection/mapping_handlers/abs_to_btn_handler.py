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


import evdev
from typing import Optional, Dict

from evdev.ecodes import EV_ABS

from inputremapper.configs.mapping import Mapping
from inputremapper.event_combination import EventCombination
from inputremapper.logger import logger
from inputremapper.input_event import InputEvent, EventActions
from inputremapper.injection.mapping_handlers.mapping_handler import MappingHandler, ContextProtocol, HandlerEnums


class AbsToBtnHandler(MappingHandler):
    """Handler which transforms an EV_ABS to a button event"""
    _input_event: InputEvent
    _active: bool

    def __init__(
            self,
            combination: EventCombination,
            mapping: Mapping,
            context: ContextProtocol,
    ):
        super().__init__(combination, mapping, context)

        self._active = False
        self._input_event = combination[0]
        assert self._input_event.value != 0
        assert len(combination) == 1

    def __str__(self):
        return f"AbsToBtnHandler for {self._input_event.event_tuple} <{id(self)}>:"

    def __repr__(self):
        return self.__str__()

    @property
    def child(self):  # used for logging
        return self._sub_handler

    def _trigger_point(self, abs_min: int, abs_max: int) -> int:
        #  TODO: potentially cash this function
        if abs_min == -1 and abs_max == 1:
            return 0  # this is a hat switch

        half_range = (abs_max - abs_min) / 2
        middle = half_range + abs_min
        trigger_offset = half_range * self._input_event.value / 100
        return int(middle + trigger_offset)

    def notify(
        self,
        event: InputEvent,
        source: evdev.InputDevice = None,
        forward: evdev.UInput = None,
        supress: bool = False,
    ) -> bool:

        if event.type_and_code != self._input_event.type_and_code:
            return False

        absinfo = {entry[0]: entry[1] for entry in source.capabilities(absinfo=True)[EV_ABS]}
        trigger_point = self._trigger_point(absinfo[event.code].min, absinfo[event.code].max)

        if self._input_event.value > 0:
            if event.value > trigger_point:
                event = event.modify(value=1, action=EventActions.as_key)
            else:
                event = event.modify(value=0, action=EventActions.as_key)
        else:
            if event.value < trigger_point:
                event = event.modify(value=1, action=EventActions.as_key)
            else:
                event = event.modify(value=0, action=EventActions.as_key)

        if bool(event.value) == self._active:
            return True  # nothing changed, consume the event

        self._active = bool(event.value)
        logger.debug_key(event.event_tuple, "sending to sub_handler")
        return self._sub_handler.notify(
            event,
            source=source,
            forward=forward,
            supress=supress,
        )
