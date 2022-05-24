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
from inputremapper.gui.event_handler import EventHandler
from inputremapper.input_event import InputEvent
from tests.test import (
    new_event,
    push_events,
    EVENT_READ_TIMEOUT,
    START_READING_DELAY,
    quick_cleanup,
    MAX_ABS,
)

import unittest
from unittest import mock
import time
import multiprocessing

from evdev.ecodes import (
    EV_KEY,
    EV_ABS,
    ABS_HAT0X,
    KEY_COMMA,
    BTN_TOOL_DOUBLETAP,
    ABS_Z,
    ABS_Y,
    KEY_A,
    EV_REL,
    REL_WHEEL,
    REL_X,
    ABS_X,
    ABS_RZ,
)

from inputremapper.gui.reader import will_report_up, Reader
from inputremapper.gui.active_preset import active_preset
from inputremapper.configs.global_config import BUTTONS, MOUSE
from inputremapper.event_combination import EventCombination
from inputremapper.gui.helper import RootHelper
from inputremapper.groups import _Groups


CODE_1 = 100
CODE_2 = 101
CODE_3 = 102


def wait(func, timeout=1.0):
    """Wait for func to return True."""
    iterations = 0
    sleepytime = 0.1
    while not func():
        time.sleep(sleepytime)
        iterations += 1
        if iterations * sleepytime > timeout:
            break


class TestReader(unittest.TestCase):
    def setUp(self):
        self.helper = None
        self.groups = _Groups()
        self.event_handler = EventHandler()
        self.reader = Reader(self.event_handler, self.groups)

    def tearDown(self):
        quick_cleanup()
        try:
            self.reader.terminate()
        except (BrokenPipeError, OSError):
            pass
        self.reader.clear()

        if self.helper is not None:
            self.helper.join()

    def create_helper(self, groups: _Groups = None):
        # this will cause pending events to be copied over to the helper
        # process
        if not groups:
            groups = self.groups

        def start_helper():
            helper = RootHelper(groups)
            helper.run()

        self.helper = multiprocessing.Process(target=start_helper)
        self.helper.start()
        time.sleep(0.1)

    def send_event_to_reader(self, event: InputEvent):
        """Act like the helper and send input events to the self.reader."""
        self.reader._results._unread.append(
            {
                "type": "event",
                "message": (event.sec, event.usec, event.type, event.code, event.value),
            }
        )

    def test_will_report_up(self):
        self.assertFalse(will_report_up(EV_REL))
        self.assertTrue(will_report_up(EV_ABS))
        self.assertTrue(will_report_up(EV_KEY))

    def test_reading_1(self):
        # a single event
        push_events("Foo Device 2", [new_event(EV_ABS, ABS_HAT0X, 1)])
        push_events(
            "Foo Device 2",
            [new_event(EV_REL, REL_X, 1)],
        )
        self.create_helper()
        self.reader.start_reading(self.groups.find(key="Foo Device 2"))
        time.sleep(0.2)
        self.assertEqual(self.reader.read(), EventCombination((EV_ABS, ABS_HAT0X, 1)))
        self.assertEqual(self.reader.read(), None)
        self.assertEqual(len(self.reader._unreleased), 1)

    def test_reading_wheel(self):
        # will be treated as released automatically at some point
        self.create_helper()
        self.reader.start_reading(self.groups.find(key="Foo Device 2"))

        self.send_event_to_reader(new_event(EV_REL, REL_WHEEL, 0))
        self.assertIsNone(self.reader.read())

        self.send_event_to_reader(new_event(EV_REL, REL_WHEEL, 1))
        result = self.reader.read()
        self.assertIsInstance(result, EventCombination)
        self.assertIsInstance(result, tuple)
        self.assertEqual(result, EventCombination((EV_REL, REL_WHEEL, 1)))
        self.assertEqual(result, ((EV_REL, REL_WHEEL, 1),))
        self.assertNotEqual(
            result,
            EventCombination(((EV_REL, REL_WHEEL, 1), (1, 1, 1))),
        )

        # it won't return the same event twice
        self.assertEqual(self.reader.read(), None)

        # but it is still remembered unreleased
        self.assertEqual(len(self.reader._unreleased), 1)
        self.assertEqual(
            self.reader.get_unreleased_keys(),
            EventCombination((EV_REL, REL_WHEEL, 1)),
        )
        self.assertIsInstance(self.reader.get_unreleased_keys(), EventCombination)

        # as long as new wheel events arrive, it is considered unreleased
        for _ in range(10):
            self.send_event_to_reader(new_event(EV_REL, REL_WHEEL, 1))
            self.assertEqual(self.reader.read(), None)
            self.assertEqual(len(self.reader._unreleased), 1)

        # read a few more times, at some point it is treated as unreleased
        for _ in range(4):
            self.assertEqual(self.reader.read(), None)
        self.assertEqual(len(self.reader._unreleased), 0)
        self.assertIsNone(self.reader.get_unreleased_keys())

        """Combinations"""

        self.send_event_to_reader(new_event(EV_REL, REL_WHEEL, 1, 1000))
        self.send_event_to_reader(new_event(EV_KEY, KEY_COMMA, 1, 1001))
        combi_1 = EventCombination(((EV_REL, REL_WHEEL, 1), (EV_KEY, KEY_COMMA, 1)))
        combi_2 = EventCombination(((EV_KEY, KEY_COMMA, 1), (EV_KEY, KEY_A, 1)))
        read = self.reader.read()
        self.assertEqual(read, combi_1)
        self.assertEqual(self.reader.read(), None)
        self.assertEqual(len(self.reader._unreleased), 2)
        self.assertEqual(self.reader.get_unreleased_keys(), combi_1)

        # don't send new wheel down events, it should get released again
        i = 0
        while len(self.reader._unreleased) == 2:
            read = self.reader.read()
            if i == 100:
                raise AssertionError("Did not release the wheel")
            i += 1
        # and only the comma remains. However, a changed combination is
        # only returned when a new key is pressed. Only then the pressed
        # down keys are collected in a new Key object.
        self.assertEqual(read, None)
        self.assertEqual(self.reader.read(), None)
        self.assertEqual(len(self.reader._unreleased), 1)
        self.assertEqual(
            self.reader.get_unreleased_keys(), EventCombination(combi_1[1])
        )

        # press down a new key, now it will return a different combination
        self.send_event_to_reader(new_event(EV_KEY, KEY_A, 1, 1002))
        self.assertEqual(self.reader.read(), combi_2)
        self.assertEqual(len(self.reader._unreleased), 2)

        # release all of them
        self.send_event_to_reader(new_event(EV_KEY, KEY_COMMA, 0))
        self.send_event_to_reader(new_event(EV_KEY, KEY_A, 0))
        self.assertEqual(self.reader.read(), None)
        self.assertEqual(len(self.reader._unreleased), 0)
        self.assertEqual(self.reader.get_unreleased_keys(), None)

    def test_change_wheel_direction(self):
        # not just wheel, anything that suddenly reports a different value.
        # as long as type and code are equal its the same key, so there is no
        # way both directions can be held down.
        self.assertEqual(self.reader.read(), None)
        self.create_helper()
        self.assertEqual(self.reader.read(), None)
        self.reader.start_reading(self.groups.find(key="Foo Device 2"))
        self.assertEqual(self.reader.read(), None)

        self.send_event_to_reader(new_event(EV_REL, REL_WHEEL, 1))
        self.assertEqual(self.reader.read(), EventCombination((EV_REL, REL_WHEEL, 1)))
        self.assertEqual(len(self.reader._unreleased), 1)
        self.assertEqual(self.reader.read(), None)

        self.send_event_to_reader(new_event(EV_REL, REL_WHEEL, -1))
        self.assertEqual(self.reader.read(), EventCombination((EV_REL, REL_WHEEL, -1)))
        # notice that this is no combination of two sides, the previous
        # entry in unreleased has to get overwritten. So there is still only
        # one element in it.
        self.assertEqual(len(self.reader._unreleased), 1)
        self.assertEqual(self.reader.read(), None)

    def test_change_device(self):
        push_events(
            "Foo Device 2",
            [
                new_event(EV_KEY, 1, 1),
            ]
            * 100,
        )

        push_events(
            "Bar Device",
            [
                new_event(EV_KEY, 2, 1),
            ]
            * 100,
        )

        self.create_helper()

        self.reader.start_reading(self.groups.find(key="Foo Device 2"))
        time.sleep(0.1)
        self.assertEqual(self.reader.read(), EventCombination((EV_KEY, 1, 1)))

        # we need to clear before we start reading, otherwise we might clear the
        # message from the new device
        self.reader.clear()
        self.reader.start_reading(self.groups.find(name="Bar Device"))
        time.sleep(0.1)
        self.assertEqual(self.reader.read(), EventCombination((EV_KEY, 2, 1)))

    def test_reading_2(self):
        # a combination of events
        push_events(
            "Foo Device 2",
            [
                new_event(EV_KEY, CODE_1, 1, 10000.1234),
                new_event(EV_KEY, CODE_3, 1, 10001.1234),
                new_event(EV_ABS, ABS_HAT0X, -1, 10002.1234),
            ],
        )

        pipe = multiprocessing.Pipe()

        def refresh():
            # from within the helper process notify this test that
            # refresh was called as expected
            pipe[1].send("refreshed")

        groups = _Groups()
        groups.refresh = refresh
        self.create_helper(groups)

        self.reader.start_reading(self.groups.find(key="Foo Device 2"))

        # sending anything arbitrary does not stop the helper
        self.reader._commands.send(856794)
        time.sleep(0.2)
        # but it makes it look for new devices because maybe its list of
        # self.groups is not up-to-date
        self.assertTrue(pipe[0].poll())
        self.assertEqual(pipe[0].recv(), "refreshed")

        self.assertEqual(
            self.reader.read(),
            ((EV_KEY, CODE_1, 1), (EV_KEY, CODE_3, 1), (EV_ABS, ABS_HAT0X, -1)),
        )
        self.assertEqual(self.reader.read(), None)
        self.assertEqual(len(self.reader._unreleased), 3)

    def test_reading_3(self):
        self.create_helper()
        # a combination of events via Socket with reads inbetween
        self.reader.start_reading(self.groups.find(name="gamepad"))

        self.send_event_to_reader(new_event(EV_KEY, CODE_1, 1, 1001))
        self.assertEqual(self.reader.read(), EventCombination((EV_KEY, CODE_1, 1)))

        # active_preset.set("gamepad.joystick.left_purpose", BUTTONS)
        self.send_event_to_reader(new_event(EV_ABS, ABS_Y, 1, 1002))
        self.assertEqual(
            self.reader.read(),
            EventCombination(((EV_KEY, CODE_1, 1), (EV_ABS, ABS_Y, 1))),
        )

        self.send_event_to_reader(new_event(EV_ABS, ABS_HAT0X, -1, 1003))
        self.assertEqual(
            self.reader.read(),
            EventCombination(
                ((EV_KEY, CODE_1, 1), (EV_ABS, ABS_Y, 1), (EV_ABS, ABS_HAT0X, -1)),
            ),
        )

        # adding duplicate down events won't report a different combination.
        # import for triggers, as they keep reporting more down-events before
        # they are released
        self.send_event_to_reader(new_event(EV_ABS, ABS_Y, 1, 1005))
        self.assertEqual(self.reader.read(), None)
        self.send_event_to_reader(new_event(EV_ABS, ABS_HAT0X, -1, 1006))
        self.assertEqual(self.reader.read(), None)

        self.send_event_to_reader(new_event(EV_KEY, CODE_1, 0, 1004))
        read = self.reader.read()
        self.assertEqual(read, None)

        self.send_event_to_reader(new_event(EV_ABS, ABS_Y, 0, 1007))
        self.assertEqual(self.reader.read(), None)

        self.send_event_to_reader(new_event(EV_KEY, ABS_HAT0X, 0, 1008))
        self.assertEqual(self.reader.read(), None)

    def test_reads_joysticks(self):
        # if their purpose is "buttons"
        # active_preset.set("gamepad.joystick.left_purpose", BUTTONS)
        push_events(
            "gamepad",
            [
                new_event(EV_ABS, ABS_Y, MAX_ABS),
                # the value of that one is interpreted as release, because
                # it is too small
                new_event(EV_ABS, ABS_X, MAX_ABS // 10),
            ],
        )
        self.create_helper()

        self.reader.start_reading(self.groups.find(name="gamepad"))
        time.sleep(0.2)
        self.assertEqual(self.reader.read(), EventCombination((EV_ABS, ABS_Y, 1)))
        self.assertEqual(self.reader.read(), None)
        self.assertEqual(len(self.reader._unreleased), 1)

        self.reader._unreleased = {}
        # active_preset.set("gamepad.joystick.left_purpose", MOUSE)
        push_events("gamepad", [new_event(EV_ABS, ABS_Y, MAX_ABS)])
        self.create_helper()

        self.reader.start_reading(self.groups.find(name="gamepad"))
        time.sleep(0.1)
        self.assertEqual(self.reader.read(), None)
        self.assertEqual(len(self.reader._unreleased), 0)

    def test_combine_triggers(self):
        self.reader.start_reading(self.groups.find(key="Foo Device 2"))

        i = 0

        def next_timestamp():
            nonlocal i
            i += 1
            return time.time() + i

        # based on an observed bug
        self.send_event_to_reader(new_event(3, 1, 0, next_timestamp()))
        self.send_event_to_reader(new_event(3, 0, 0, next_timestamp()))
        self.send_event_to_reader(new_event(3, 2, 1, next_timestamp()))
        self.assertEqual(self.reader.read(), EventCombination((EV_ABS, ABS_Z, 1)))
        self.send_event_to_reader(new_event(3, 0, 0, next_timestamp()))
        self.send_event_to_reader(new_event(3, 5, 1, next_timestamp()))
        self.assertEqual(
            self.reader.read(),
            EventCombination(((EV_ABS, ABS_Z, 1), (EV_ABS, ABS_RZ, 1))),
        )
        self.send_event_to_reader(new_event(3, 5, 0, next_timestamp()))
        self.send_event_to_reader(new_event(3, 0, 0, next_timestamp()))
        self.send_event_to_reader(new_event(3, 1, 0, next_timestamp()))
        self.assertEqual(self.reader.read(), None)
        self.send_event_to_reader(new_event(3, 2, 1, next_timestamp()))
        self.send_event_to_reader(new_event(3, 1, 0, next_timestamp()))
        self.send_event_to_reader(new_event(3, 0, 0, next_timestamp()))
        # due to not properly handling the duplicate down event it cleared
        # the combination and returned it. Instead it should report None
        # and by doing that keep the previous combination.
        self.assertEqual(self.reader.read(), None)

    def test_blacklisted_events(self):
        push_events(
            "Foo Device 2",
            [
                new_event(EV_KEY, BTN_TOOL_DOUBLETAP, 1),
                new_event(EV_KEY, CODE_2, 1),
                new_event(EV_KEY, BTN_TOOL_DOUBLETAP, 1),
            ],
        )
        self.create_helper()
        self.reader.start_reading(self.groups.find(key="Foo Device 2"))
        time.sleep(0.1)
        self.assertEqual(self.reader.read(), EventCombination((EV_KEY, CODE_2, 1)))
        self.assertEqual(self.reader.read(), None)
        self.assertEqual(len(self.reader._unreleased), 1)

    def test_ignore_value_2(self):
        # this is not a combination, because (EV_KEY CODE_3, 2) is ignored
        push_events(
            "Foo Device 2",
            [new_event(EV_ABS, ABS_HAT0X, 1), new_event(EV_KEY, CODE_3, 2)],
        )
        self.create_helper()
        self.reader.start_reading(self.groups.find(key="Foo Device 2"))
        time.sleep(0.2)
        self.assertEqual(self.reader.read(), EventCombination((EV_ABS, ABS_HAT0X, 1)))
        self.assertEqual(self.reader.read(), None)
        self.assertEqual(len(self.reader._unreleased), 1)

    def test_reading_ignore_up(self):
        push_events(
            "Foo Device 2",
            [
                new_event(EV_KEY, CODE_1, 0, 10),
                new_event(EV_KEY, CODE_2, 1, 11),
                new_event(EV_KEY, CODE_3, 0, 12),
            ],
        )
        self.create_helper()
        self.reader.start_reading(self.groups.find(key="Foo Device 2"))
        time.sleep(0.1)
        self.assertEqual(self.reader.read(), EventCombination((EV_KEY, CODE_2, 1)))
        self.assertEqual(self.reader.read(), None)
        self.assertEqual(len(self.reader._unreleased), 1)

    def test_reading_ignore_duplicate_down(self):
        self.reader.start_reading(self.groups.find(key="Foo Device 2"))
        self.send_event_to_reader(new_event(EV_ABS, ABS_Z, 1, 10))

        self.assertEqual(self.reader.read(), EventCombination((EV_ABS, ABS_Z, 1)))
        self.assertEqual(self.reader.read(), None)

        # duplicate
        self.send_event_to_reader(new_event(EV_ABS, ABS_Z, 1, 10))
        self.assertEqual(self.reader.read(), None)
        self.assertEqual(len(self.reader._unreleased), 1)
        self.assertEqual(len(self.reader.get_unreleased_keys()), 1)
        self.assertIsInstance(self.reader.get_unreleased_keys(), EventCombination)

        # release
        self.send_event_to_reader(new_event(EV_ABS, ABS_Z, 0, 10))
        self.assertEqual(self.reader.read(), None)
        self.assertEqual(len(self.reader._unreleased), 0)
        self.assertIsNone(self.reader.get_unreleased_keys())

    def test_wrong_device(self):
        push_events(
            "Foo Device 2",
            [
                new_event(EV_KEY, CODE_1, 1),
                new_event(EV_KEY, CODE_2, 1),
                new_event(EV_KEY, CODE_3, 1),
            ],
        )
        self.create_helper()
        self.reader.start_reading(self.groups.find(name="Bar Device"))
        time.sleep(EVENT_READ_TIMEOUT * 5)
        self.assertEqual(self.reader.read(), None)
        self.assertEqual(len(self.reader._unreleased), 0)

    def test_inputremapper_devices(self):
        # Don't read from inputremapper devices, their keycodes are not
        # representative for the original key. As long as this is not
        # intentionally programmed it won't even do that. But it was at some
        # point.
        push_events(
            "input-remapper Bar Device",
            [
                new_event(EV_KEY, CODE_1, 1),
                new_event(EV_KEY, CODE_2, 1),
                new_event(EV_KEY, CODE_3, 1),
            ],
        )
        self.create_helper()
        self.reader.start_reading(self.groups.find(name="Bar Device"))
        time.sleep(EVENT_READ_TIMEOUT * 5)
        self.assertEqual(self.reader.read(), None)
        self.assertEqual(len(self.reader._unreleased), 0)

    def test_clear(self):
        push_events(
            "Foo Device 2",
            [
                new_event(EV_KEY, CODE_1, 1),
                new_event(EV_KEY, CODE_2, 1),
                new_event(EV_KEY, CODE_3, 1),
            ]
            * 15,
        )

        self.create_helper()
        self.reader.start_reading(self.groups.find(key="Foo Device 2"))
        time.sleep(START_READING_DELAY + EVENT_READ_TIMEOUT * 3)

        self.reader.read()
        self.assertEqual(len(self.reader._unreleased), 3)
        self.assertIsNotNone(self.reader.previous_event)
        self.assertIsNotNone(self.reader.previous_result)

        # make the helper send more events to the self.reader
        push_events(
            "Foo Device 2", [new_event(EV_KEY, CODE_3, 0), new_event(EV_KEY, CODE_3, 0)]
        )
        time.sleep(EVENT_READ_TIMEOUT * 2)
        self.assertTrue(self.reader._results.poll())
        self.reader.clear()

        self.assertFalse(self.reader._results.poll())
        self.assertEqual(self.reader.read(), None)
        self.assertEqual(len(self.reader._unreleased), 0)
        self.assertIsNone(self.reader.get_unreleased_keys())
        self.assertIsNone(self.reader.previous_event)
        self.assertIsNone(self.reader.previous_result)
        self.tearDown()

    def test_switch_device(self):
        push_events("Bar Device", [new_event(EV_KEY, CODE_1, 1)])
        push_events("Foo Device 2", [new_event(EV_KEY, CODE_3, 1)])
        self.create_helper()

        self.reader.start_reading(self.groups.find(name="Bar Device"))
        self.assertFalse(self.reader._results.poll())
        self.assertEqual(self.reader.group.name, "Bar Device")
        time.sleep(EVENT_READ_TIMEOUT * 5)

        self.assertTrue(self.reader._results.poll())
        self.reader.start_reading(self.groups.find(key="Foo Device 2"))
        self.assertEqual(self.reader.group.name, "Foo Device")
        self.assertFalse(self.reader._results.poll())  # pipe resets

        time.sleep(EVENT_READ_TIMEOUT * 5)
        self.assertTrue(self.reader._results.poll())

        self.assertEqual(self.reader.read(), EventCombination((EV_KEY, CODE_3, 1)))
        self.assertEqual(self.reader.read(), None)
        self.assertEqual(len(self.reader._unreleased), 1)

    def test_terminate(self):
        self.create_helper()
        self.reader.start_reading(self.groups.find(key="Foo Device 2"))

        push_events("Foo Device 2", [new_event(EV_KEY, CODE_3, 1)])
        time.sleep(START_READING_DELAY + EVENT_READ_TIMEOUT)
        self.assertTrue(self.reader._results.poll())

        self.reader.terminate()
        self.reader.clear()
        time.sleep(EVENT_READ_TIMEOUT)

        # no new events arrive after terminating
        push_events("Foo Device 2", [new_event(EV_KEY, CODE_3, 1)])
        time.sleep(EVENT_READ_TIMEOUT * 3)
        self.assertFalse(self.reader._results.poll())

    def test_are_new_groups_available(self):
        self.create_helper()
        self.groups.set_groups({})
        print(self.groups._groups)
        print(self.reader.groups._groups)

        # read stuff from the helper, which includes the devices
        self.assertFalse(self.reader.are_new_groups_available())
        self.reader.read()

        self.assertTrue(self.reader.are_new_groups_available())
        # a bit weird, but it assumes the gui handled that and returns
        # false afterwards
        self.assertFalse(self.reader.are_new_groups_available())

        # send the same devices again
        self.reader._get_event({"type": "groups", "message": self.groups.dumps()})
        self.assertFalse(self.reader.are_new_groups_available())

        # send changed devices
        message = self.groups.dumps()
        message = message.replace("Foo Device", "foo_device")
        self.reader._get_event({"type": "groups", "message": message})
        self.assertTrue(self.reader.are_new_groups_available())
        self.assertFalse(self.reader.are_new_groups_available())


if __name__ == "__main__":
    unittest.main()
