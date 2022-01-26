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


"""Executes more complex patterns of keystrokes.

To keep it short on the UI, basic functions are one letter long.

The outermost macro (in the examples below the one created by 'r',
'r' and 'w') will be started, which triggers a chain reaction to execute
all of the configured stuff.

Examples
--------
r(3, k(a).w(10)): a <10ms> a <10ms> a
r(2, k(a).k(KEY_A)).k(b): a - a - b
w(1000).m(Shift_L, r(2, k(a))).w(10).k(b): <1s> A A <10ms> b
"""


import asyncio
import copy
import re
from typing import Optional

import evdev
from evdev.ecodes import ecodes, EV_KEY, EV_REL, REL_X, REL_Y, REL_WHEEL, REL_HWHEEL

from inputremapper.logger import logger
from inputremapper.configs.system_mapping import system_mapping
from inputremapper.ipc.shared_dict import SharedDict
from inputremapper.exceptions import MacroParsingError


macro_variables = SharedDict()


class Variable:
    """Can be used as function parameter in the various add_... functions.

    Parsed from strings like `$foo` in `repeat($foo, k(KEY_A))`

    Its value is unknown during construction and needs to be set using the `set` macro
    during runtime.
    """

    def __init__(self, name):
        self.name = name

    def resolve(self):
        """Get the variables value from memory."""
        return macro_variables.get(self.name)

    def __repr__(self):
        return f'<Variable "{self.name}">'


def _type_check(value, allowed_types, display_name=None, position=None):
    """Validate a parameter used in a macro.

    If the value is a Variable, it will be returned and should be resolved
    during runtime with _resolve.
    """
    if isinstance(value, Variable):
        # it is a variable and will be read at runtime
        return value

    for allowed_type in allowed_types:
        if allowed_type is None:
            if value is None:
                return value

            continue

        # try to parse "1" as 1 if possible
        try:
            return allowed_type(value)
        except (TypeError, ValueError):
            pass

        if isinstance(value, allowed_type):
            return value

    if display_name is not None and position is not None:
        raise MacroParsingError(
            msg=f"Expected parameter {position} for {display_name} to be "
            f"one of {allowed_types}, but got {value}"
        )

    raise MacroParsingError(
        msg=f"Expected parameter to be one of {allowed_types}, but got {value}"
    )


def _type_check_keyname(keyname):
    """Same as _type_check, but checks if the key-name is valid."""
    if isinstance(keyname, Variable):
        # it is a variable and will be read at runtime
        return keyname

    symbol = str(keyname)
    code = system_mapping.get(symbol)

    if code is None:
        raise MacroParsingError(msg=f'Unknown key "{symbol}"')

    return code


def _type_check_variablename(name):
    """Check if this is a legit variable name.

    Because they could clash with language features. If the macro is able to be
    parsed at all due to a problematic choice of a variable name.

    Allowed examples: "foo", "Foo1234_", "_foo_1234"
    Not allowed: "1_foo", "foo=blub", "$foo", "foo,1234", "foo()"
    """
    if not isinstance(name, str) or not re.match(r"^[A-Za-z_][A-Za-z_0-9]*$", name):
        raise MacroParsingError(msg=f'"{name}" is not a legit variable name')


def _resolve(argument, allowed_types=None):
    """If the argument is a variable, figure out its value and cast it.

    Use this just-in-time when you need the actual value of the variable
    during runtime.
    """
    if isinstance(argument, Variable):
        value = argument.resolve()
        logger.debug('"%s" is "%s"', argument, value)
        if allowed_types:
            return _type_check(value, allowed_types)
        else:
            return value

    return argument


class Macro:
    """Supports chaining and preparing actions.

    Calling functions like keycode on Macro doesn't inject any events yet,
    it means that once .run is used it will be executed along with all other
    queued tasks.

    Those functions need to construct an asyncio coroutine and append it to
    self.tasks. This makes parameter checking during compile time possible, as long
    as they are not variables that are resolved durig runtime. Coroutines receive a
    handler as argument, which is a function that can be used to inject input events
    into the system.

    1. A few parameters of any time are thrown into a macro function like `repeat`
    2. `Macro.repeat` will verify the parameter types if possible using `_type_check`
       (it can't for $variables). This helps debugging macros before the injection
       starts, but is not mandatory to make things work.
    3. `Macro.repeat`
       - adds a task to self.tasks. This task resolves any variables with `_resolve`
         and does what the macro is supposed to do once `macro.run` is called.
       - also adds the child macro to self.child_macros.
       - adds the used keys to the capabilities
    4. `Macro.run` will run all tasks in self.tasks
    """

    _triggering_event: Optional[evdev.InputEvent]

    def __init__(self, code, context):
        """Create a macro instance that can be populated with tasks.

        Parameters
        ----------
        code : string or None
            The original parsed code, for logging purposes.
        context : Context, or None for use in frontend
        """
        self.code = code
        self.context = context

        # List of coroutines that will be called sequentially.
        # This is the compiled code
        self.tasks = []

        # can be used to wait for the release of the event
        self._trigger_release_event = asyncio.Event()
        self._trigger_press_event = asyncio.Event()
        # released by default
        self._trigger_release_event.set()
        self._trigger_press_event.clear()

        self.running = False

        # all required capabilities, without those of child macros
        self.capabilities = {
            EV_KEY: set(),
            EV_REL: set(),
        }

        self.child_macros = []

        self.keystroke_sleep_ms = None
        self._triggering_event = None

    def is_holding(self):
        """Check if the macro is waiting for a key to be released."""
        return not self._trigger_release_event.is_set()

    def get_capabilities(self):
        """Get the merged capabilities of the macro and its children."""
        capabilities = copy.deepcopy(self.capabilities)

        for macro in self.child_macros:
            macro_capabilities = macro.get_capabilities()
            for ev_type in macro_capabilities:
                if ev_type not in capabilities:
                    capabilities[ev_type] = set()

                capabilities[ev_type].update(macro_capabilities[ev_type])

        return capabilities

    async def run(self, handler):
        """Run the macro.

        Parameters
        ----------
        handler : function
            Will receive int type, code and value for an event to write
        """
        if not callable(handler):
            raise ValueError("handler is not callable")

        if self.running:
            logger.error('Tried to run already running macro "%s"', self.code)
            return

        self.keystroke_sleep_ms = self.context.preset.get("macros.keystroke_sleep_ms")

        self.running = True
        for task in self.tasks:
            try:
                coroutine = task(handler)
                if asyncio.iscoroutine(coroutine):
                    await coroutine
            except Exception as e:
                logger.error(f'Macro "%s" failed: %s', self.code, e)
                break

        # done
        self.running = False

    def press_trigger(self, event: evdev.InputEvent):
        """The user pressed the trigger key down."""
        if self.is_holding():
            logger.error("Already holding")
            return

        self._triggering_event = event
        self._trigger_release_event.clear()
        self._trigger_press_event.set()

        for macro in self.child_macros:
            macro.press_trigger(event)

    def release_trigger(self):
        """The user released the trigger key."""
        self._trigger_release_event.set()
        self._trigger_press_event.clear()

        for macro in self.child_macros:
            macro.release_trigger()

    async def _keycode_pause(self, _=None):
        """To add a pause between keystrokes."""
        await asyncio.sleep(self.keystroke_sleep_ms / 1000)

    def add_mouse_capabilities(self):
        """Add all capabilities that are required to recognize the device as mouse."""
        self.capabilities[EV_REL].add(REL_X)
        self.capabilities[EV_REL].add(REL_Y)
        self.capabilities[EV_REL].add(REL_WHEEL)
        self.capabilities[EV_REL].add(REL_HWHEEL)

    def __repr__(self):
        return f'<Macro "{self.code}">'

    """Functions that prepare the macro"""

    def add_hold(self, macro=None):
        """Loops the execution until key release."""
        _type_check(macro, [Macro, str, None], "h (hold)", 1)

        if macro is None:
            self.tasks.append(lambda _: self._trigger_release_event.wait())
            return

        if not isinstance(macro, Macro):
            # if macro is a key name, hold down the key while the
            # keyboard key is physically held down
            code = _type_check_keyname(macro)

            async def task(handler):
                resolved_code = _resolve(code, [int])
                self.capabilities[EV_KEY].add(resolved_code)
                handler(EV_KEY, resolved_code, 1)
                await self._trigger_release_event.wait()
                handler(EV_KEY, resolved_code, 0)

            self.capabilities[EV_KEY].add(code)
            self.tasks.append(task)

        if isinstance(macro, Macro):
            # repeat the macro forever while the key is held down
            async def task(handler):
                while self.is_holding():
                    # run the child macro completely to avoid
                    # not-releasing any key
                    await macro.run(handler)

            self.tasks.append(task)
            self.child_macros.append(macro)

    def add_modify(self, modifier, macro):
        """Do stuff while a modifier is activated.

        Parameters
        ----------
        modifier : str
        macro : Macro
        """
        _type_check(macro, [Macro], "m (modify)", 2)

        modifier = str(modifier)
        code = system_mapping.get(modifier)

        if code is None:
            raise MacroParsingError(self.code, f'Unknown modifier "{modifier}"')

        self.capabilities[EV_KEY].add(code)

        self.child_macros.append(macro)

        async def task(handler):
            resolved_code = _resolve(code, [int])
            self.capabilities[EV_KEY].add(resolved_code)
            await self._keycode_pause()
            handler(EV_KEY, resolved_code, 1)
            await self._keycode_pause()
            await macro.run(handler)
            await self._keycode_pause()
            handler(EV_KEY, resolved_code, 0)
            await self._keycode_pause()

        self.tasks.append(task)

    def add_repeat(self, repeats, macro):
        """Repeat actions.

        Parameters
        ----------
        repeats : int or Macro
        macro : Macro
        """
        repeats = _type_check(repeats, [int], "r (repeat)", 1)
        _type_check(macro, [Macro], "r (repeat)", 2)

        async def task(handler):
            for _ in range(_resolve(repeats, [int])):
                await macro.run(handler)

        self.tasks.append(task)
        self.child_macros.append(macro)

    def add_key(self, symbol):
        """Write the symbol."""
        _type_check_keyname(symbol)

        symbol = str(symbol)
        code = system_mapping.get(symbol)
        self.capabilities[EV_KEY].add(code)

        async def task(handler):
            handler(EV_KEY, code, 1)
            await self._keycode_pause()
            handler(EV_KEY, code, 0)
            await self._keycode_pause()

        self.tasks.append(task)

    def add_event(self, _type, code, value):
        """Write any event.

        Parameters
        ----------
        _type: str or int
            examples: 2, 'EV_KEY'
        code : int or int
            examples: 52, 'KEY_A'
        value : int
        """
        _type = _type_check(_type, [int, str], "e (event)", 1)
        code = _type_check(code, [int, str], "e (event)", 2)
        value = _type_check(value, [int, str], "e (event)", 3)

        if isinstance(_type, str):
            _type = ecodes[_type.upper()]
        if isinstance(code, str):
            code = ecodes[code.upper()]

        if _type not in self.capabilities:
            self.capabilities[_type] = set()

        if _type == EV_REL:
            # add all capabilities that are required for the display server
            # to recognize the device as mouse
            self.capabilities[EV_REL].add(REL_X)
            self.capabilities[EV_REL].add(REL_Y)
            self.capabilities[EV_REL].add(REL_WHEEL)

        self.capabilities[_type].add(code)

        self.tasks.append(lambda handler: handler(_type, code, value))
        self.tasks.append(self._keycode_pause)

    def add_mouse(self, direction, speed):
        """Move the mouse cursor."""
        _type_check(direction, [str], "mouse", 1)
        speed = _type_check(speed, [int], "mouse", 2)

        code, value = {
            "up": (REL_Y, -1),
            "down": (REL_Y, 1),
            "left": (REL_X, -1),
            "right": (REL_X, 1),
        }[direction.lower()]

        self.add_mouse_capabilities()

        async def task(handler):
            resolved_speed = value * _resolve(speed, [int])
            while self.is_holding():
                handler(EV_REL, code, resolved_speed)
                await self._keycode_pause()

        self.tasks.append(task)

    def add_wheel(self, direction, speed):
        """Move the scroll wheel."""
        _type_check(direction, [str], "wheel", 1)
        speed = _type_check(speed, [int], "wheel", 2)

        code, value = {
            "up": (REL_WHEEL, 1),
            "down": (REL_WHEEL, -1),
            "left": (REL_HWHEEL, 1),
            "right": (REL_HWHEEL, -1),
        }[direction.lower()]

        self.add_mouse_capabilities()

        async def task(handler):
            resolved_speed = _resolve(speed, [int])
            while self.is_holding():
                handler(EV_REL, code, value)
                # scrolling moves much faster than mouse, so this
                # waits between injections instead to make it slower
                await asyncio.sleep(1 / resolved_speed)

        self.tasks.append(task)

    def add_wait(self, time):
        """Wait time in milliseconds."""
        time = _type_check(time, [int, float], "wait", 1)

        async def task(_):
            await asyncio.sleep(_resolve(time, [int, float]) / 1000)

        self.tasks.append(task)

    def add_set(self, variable, value):
        """Set a variable to a certain value."""
        _type_check_variablename(variable)

        async def task(_):
            # can also copy with set(a, $b)
            resolved_value = _resolve(value)
            logger.debug('"%s" set to "%s"', variable, resolved_value)
            macro_variables[variable] = value

        self.tasks.append(task)

    def add_ifeq(self, variable, value, then=None, otherwise=None):
        """Old version of if_eq, kept for compatibility reasons.

        This can't support a comparison like ifeq("foo", $blub) with blub containing
        "foo" without breaking old functionality, because "foo" is treated as a
        variable name.
        """
        _type_check(then, [Macro, None], "ifeq", 3)
        _type_check(otherwise, [Macro, None], "ifeq", 4)

        async def task(handler):
            set_value = macro_variables.get(variable)
            logger.debug('"%s" is "%s"', variable, set_value)
            if set_value == value:
                if then is not None:
                    await then.run(handler)
            elif otherwise is not None:
                await otherwise.run(handler)

        if isinstance(then, Macro):
            self.child_macros.append(then)
        if isinstance(otherwise, Macro):
            self.child_macros.append(otherwise)

        self.tasks.append(task)

    def add_if_eq(self, value_1, value_2, then=None, _else=None):
        """Compare two values."""
        _type_check(then, [Macro, None], "if_eq", 3)
        _type_check(_else, [Macro, None], "if_eq", 4)

        async def task(handler):
            resolved_value_1 = _resolve(value_1)
            resolved_value_2 = _resolve(value_2)
            if resolved_value_1 == resolved_value_2:
                if then is not None:
                    await then.run(handler)
            elif _else is not None:
                await _else.run(handler)

        if isinstance(then, Macro):
            self.child_macros.append(then)
        if isinstance(_else, Macro):
            self.child_macros.append(_else)

        self.tasks.append(task)

    def add_if_tap(self, then=None, _else=None, timeout=300):
        """If a key was pressed quickly.

        macro key pressed -> if_tap starts -> key released -> then

        macro key pressed -> released (does other stuff in the meantime)
        -> if_tap starts -> pressed -> released -> then
        """
        _type_check(then, [Macro, None], "if_tap", 1)
        _type_check(_else, [Macro, None], "if_tap", 2)
        timeout = _type_check(timeout, [int, float], "if_tap", 3)

        if isinstance(then, Macro):
            self.child_macros.append(then)
        if isinstance(_else, Macro):
            self.child_macros.append(_else)

        async def wait():
            """Wait for a release, or if nothing pressed yet, a press and release."""
            if self.is_holding():
                await self._trigger_release_event.wait()
            else:
                await self._trigger_press_event.wait()
                await self._trigger_release_event.wait()

        async def task(handler):
            resolved_timeout = _resolve(timeout, [int, float]) / 1000
            try:
                await asyncio.wait_for(wait(), resolved_timeout)
                if then:
                    await then.run(handler)
            except asyncio.TimeoutError:
                if _else:
                    await _else.run(handler)

        self.tasks.append(task)

    def add_if_single(self, then, _else, timeout=None):
        """If a key was pressed without combining it."""
        # TODO migrate "otherwise" to "else"
        _type_check(then, [Macro, None], "if_single", 1)
        _type_check(_else, [Macro, None], "if_single", 2)

        if isinstance(then, Macro):
            self.child_macros.append(then)
        if isinstance(_else, Macro):
            self.child_macros.append(_else)

        async def task(handler):
            trigger_code = self._triggering_event.code

            listener_done = asyncio.Event()

            success = False

            async def listener(event):
                nonlocal success

                if event.type != EV_KEY:
                    # ignore anything that is not a key
                    return

                if event.code != trigger_code and event.value == 1:
                    # another key was pressed, trigger else
                    listener_done.set()
                    return

                if event.code == trigger_code and event.value == 0:
                    # the trigger was released
                    success = True
                    listener_done.set()
                    return

            self.context.listeners.add(listener)

            try:
                resolved_timeout = _resolve(timeout, allowed_types=[int, float, None])
                await asyncio.wait_for(
                    listener_done.wait(),
                    resolved_timeout / 1000 if resolved_timeout else None,
                )
            except asyncio.TimeoutError:
                pass

            self.context.listeners.remove(listener)

            if success:
                await then.run(handler)
            else:
                await _else.run(handler)

        self.tasks.append(task)
