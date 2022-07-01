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
import builtins
import json
import os.path
import unittest
from dataclasses import dataclass
from unittest.mock import patch, MagicMock
from typing import Tuple, List, Any

import gi

from inputremapper.injection.injector import (
    RUNNING,
    FAILED,
    NO_GRAB,
    UPGRADE_EVDEV,
    UNKNOWN,
)
from inputremapper.input_event import InputEvent

gi.require_version("Gtk", "3.0")
gi.require_version("GLib", "2.0")
gi.require_version("GtkSource", "4")
from gi.repository import Gtk

# from inputremapper.gui.helper import is_helper_running
from inputremapper.event_combination import EventCombination
from inputremapper.groups import _Groups
from inputremapper.gui.message_broker import (
    MessageBroker,
    MessageType,
    Signal,
    UInputsData,
    GroupsData,
    GroupData,
    PresetData,
    StatusData,
    CombinationUpdate,
    CombinationRecorded,
)
from inputremapper.gui.reader import Reader
from inputremapper.gui.utils import CTX_ERROR, CTX_APPLY
from inputremapper.gui.gettext import _
from inputremapper.injection.global_uinputs import GlobalUInputs
from inputremapper.configs.mapping import Mapping, UIMapping, MappingData
from tests.test import (
    quick_cleanup,
    get_key_mapping,
    FakeDaemonProxy,
    fixtures,
    prepare_presets,
)
from inputremapper.configs.global_config import global_config, GlobalConfig
from inputremapper.gui.controller import Controller, MAPPING_DEFAULTS
from inputremapper.gui.data_manager import DataManager, DEFAULT_PRESET_NAME
from inputremapper.configs.paths import get_preset_path, get_config_path
from inputremapper.configs.preset import Preset


class TestController(unittest.TestCase):
    def setUp(self) -> None:
        super(TestController, self).setUp()
        self.message_broker = MessageBroker()
        uinputs = GlobalUInputs()
        uinputs.prepare_all()
        self.data_manager = DataManager(
            self.message_broker,
            GlobalConfig(),
            Reader(self.message_broker, _Groups()),
            FakeDaemonProxy(),
            uinputs,
        )
        self.user_interface = MagicMock()
        self.controller = Controller(self.message_broker, self.data_manager)
        self.controller.set_gui(self.user_interface)

    def tearDown(self) -> None:
        quick_cleanup()

    def test_should_get_newest_group(self):
        """get_a_group should the newest group"""
        with patch.object(
            self.data_manager, "get_newest_group_key", MagicMock(return_value="foo")
        ):
            self.assertEqual(self.controller.get_a_group(), "foo")

    def test_should_get_any_group(self):
        """get_a_group should return a valid group"""
        with patch.object(
            self.data_manager,
            "get_newest_group_key",
            MagicMock(side_effect=FileNotFoundError),
        ):
            fixture_keys = [
                fixture.get("group_key") or fixture.get("name")
                for fixture in fixtures.values()
            ]
            self.assertIn(self.controller.get_a_group(), fixture_keys)

    def test_should_get_newest_preset(self):
        """get_a_group should the newest group"""
        with patch.object(
            self.data_manager, "get_newest_preset_name", MagicMock(return_value="bar")
        ):
            self.data_manager.load_group("Foo Device")
            self.assertEqual(self.controller.get_a_preset(), "bar")

    def test_should_get_any_preset(self):
        """get_a_preset should return a new preset if none exist"""
        self.data_manager.load_group("Foo Device")
        self.assertEqual(
            self.controller.get_a_preset(), "new preset"
        )  # the default name

    def test_on_init_should_provide_uinputs(self):
        calls = []

        def f(data):
            calls.append(data)

        self.message_broker.subscribe(MessageType.uinputs, f)
        self.message_broker.signal(MessageType.init)
        self.assertEqual(
            ["keyboard", "gamepad", "mouse", "keyboard + mouse"],
            list(calls[-1].uinputs.keys()),
        )

    def test_on_init_should_provide_groups(self):
        calls: List[GroupsData] = []

        def f(groups):
            calls.append(groups)

        self.message_broker.subscribe(MessageType.groups, f)
        self.message_broker.signal(MessageType.init)
        self.assertEqual(
            ["Foo Device", "Foo Device 2", "Bar Device", "gamepad"],
            list(calls[-1].groups.keys()),
        )

    def test_on_init_should_provide_a_group(self):
        calls: List[GroupData] = []

        def f(data):
            calls.append(data)

        self.message_broker.subscribe(MessageType.group, f)
        self.message_broker.signal(MessageType.init)
        self.assertGreaterEqual(len(calls), 1)

    def test_on_init_should_provide_a_preset(self):
        calls: List[PresetData] = []

        def f(data):
            calls.append(data)

        self.message_broker.subscribe(MessageType.preset, f)
        self.message_broker.signal(MessageType.init)
        self.assertGreaterEqual(len(calls), 1)

    def test_on_init_should_provide_a_mapping(self):
        """only if there is one"""
        prepare_presets()
        calls: List[MappingData] = []

        def f(data):
            calls.append(data)

        self.message_broker.subscribe(MessageType.mapping, f)
        self.message_broker.signal(MessageType.init)
        self.assertTrue(calls[-1].is_valid())

    def test_on_init_should_provide_a_default_mapping(self):
        """if there is no real preset available"""
        calls: List[MappingData] = []

        def f(data):
            calls.append(data)

        self.message_broker.subscribe(MessageType.mapping, f)
        self.message_broker.signal(MessageType.init)
        for m in calls:
            self.assertEqual(m, UIMapping(**MAPPING_DEFAULTS))

    def test_on_init_should_provide_status_if_helper_is_not_running(self):
        calls: List[StatusData] = []

        def f(data):
            calls.append(data)

        self.message_broker.subscribe(MessageType.status, f)
        with patch("inputremapper.gui.controller.is_helper_running", lambda: False):
            self.message_broker.signal(MessageType.init)
        self.assertIn(StatusData(CTX_ERROR, _("The helper did not start")), calls)

    def test_on_init_should_not_provide_status_if_helper_is_running(self):
        calls: List[StatusData] = []

        def f(data):
            calls.append(data)

        self.message_broker.subscribe(MessageType.status, f)
        with patch("inputremapper.gui.controller.is_helper_running", lambda: True):
            self.message_broker.signal(MessageType.init)

        self.assertNotIn(StatusData(CTX_ERROR, _("The helper did not start")), calls)

    def test_on_load_group_should_provide_preset(self):
        with patch.object(self.data_manager, "load_preset") as mock:
            self.controller.load_group("Foo Device")
            mock.assert_called_once()

    def test_on_load_group_should_provide_mapping(self):
        """if there is one"""
        prepare_presets()
        calls: List[MappingData] = []

        def f(data):
            calls.append(data)

        self.message_broker.subscribe(MessageType.mapping, f)
        self.controller.load_group(group_key="Foo Device 2")
        self.assertTrue(calls[-1].is_valid())

    def test_on_load_group_should_provide_default_mapping(self):
        """if there is none"""
        calls: List[MappingData] = []

        def f(data):
            calls.append(data)

        self.message_broker.subscribe(MessageType.mapping, f)

        self.controller.load_group(group_key="Foo Device")
        for m in calls:
            self.assertEqual(m, UIMapping(**MAPPING_DEFAULTS))

    def test_on_load_preset_should_provide_mapping(self):
        """if there is one"""
        prepare_presets()
        self.data_manager.load_group("Foo Device 2")
        calls: List[MappingData] = []

        def f(data):
            calls.append(data)

        self.message_broker.subscribe(MessageType.mapping, f)
        self.controller.load_preset(name="preset2")
        self.assertTrue(calls[-1].is_valid())

    def test_on_load_preset_should_provide_default_mapping(self):
        """if there is none"""
        Preset(get_preset_path("Foo Device", "bar")).save()
        self.data_manager.load_group("Foo Device 2")
        calls: List[MappingData] = []

        def f(data):
            calls.append(data)

        self.message_broker.subscribe(MessageType.mapping, f)
        self.controller.load_preset(name="bar")
        for m in calls:
            self.assertEqual(m, UIMapping(**MAPPING_DEFAULTS))

    def test_on_delete_preset_asks_for_confirmation(self):
        prepare_presets()
        with patch.object(self.user_interface, "confirm_delete") as mock:
            self.message_broker.signal(MessageType.init)
            self.controller.delete_preset()
            mock.assert_called_once()

    def test_deletes_preset_when_confirmed(self):
        prepare_presets()
        self.assertTrue(os.path.isfile(get_preset_path("Foo Device", "preset2")))

        self.data_manager.load_group("Foo Device 2")
        self.data_manager.load_preset("preset2")
        self.user_interface.confirm_delete.configure_mock(
            return_value=Gtk.ResponseType.ACCEPT
        )
        self.controller.delete_preset()
        self.assertFalse(os.path.exists(get_preset_path("Foo Device", "preset2")))

    def test_does_not_delete_preset_when_not_confirmed(self):
        prepare_presets()
        self.assertTrue(os.path.isfile(get_preset_path("Foo Device", "preset2")))
        self.data_manager.load_group("Foo Device 2")
        self.data_manager.load_preset("preset2")
        self.user_interface.confirm_delete.configure_mock(
            return_value=Gtk.ResponseType.CANCEL
        )
        self.controller.delete_preset()
        self.assertTrue(os.path.isfile(get_preset_path("Foo Device", "preset2")))

    def test_copy_preset(self):
        prepare_presets()
        self.assertTrue(os.path.isfile(get_preset_path("Foo Device", "preset2")))
        self.data_manager.load_group("Foo Device 2")
        self.data_manager.load_preset("preset2")
        self.controller.copy_preset()

        self.assertTrue(os.path.exists(get_preset_path("Foo Device", "preset2")))
        self.assertTrue(os.path.exists(get_preset_path("Foo Device", "preset2 copy")))

    def test_copy_preset_should_add_number(self):
        prepare_presets()
        self.assertTrue(os.path.isfile(get_preset_path("Foo Device", "preset2")))

        self.data_manager.load_group("Foo Device 2")
        self.data_manager.load_preset("preset2")
        self.controller.copy_preset()  # creates "preset2 copy"
        self.data_manager.load_preset("preset2")
        self.controller.copy_preset()  # creates "preset2 copy 2"

        self.assertTrue(os.path.exists(get_preset_path("Foo Device", "preset2")))
        self.assertTrue(os.path.exists(get_preset_path("Foo Device", "preset2 copy")))
        self.assertTrue(os.path.exists(get_preset_path("Foo Device", "preset2 copy 2")))

    def test_copy_preset_should_increment_existing_number(self):
        prepare_presets()
        self.assertTrue(os.path.isfile(get_preset_path("Foo Device", "preset2")))

        self.data_manager.load_group("Foo Device 2")
        self.data_manager.load_preset("preset2")
        self.controller.copy_preset()  # creates "preset2 copy"
        self.data_manager.load_preset("preset2")
        self.controller.copy_preset()  # creates "preset2 copy 2"
        self.data_manager.load_preset("preset2")
        self.controller.copy_preset()  # creates "preset2 copy 3"

        self.assertTrue(os.path.exists(get_preset_path("Foo Device", "preset2")))
        self.assertTrue(os.path.exists(get_preset_path("Foo Device", "preset2 copy")))
        self.assertTrue(os.path.exists(get_preset_path("Foo Device", "preset2 copy 2")))
        self.assertTrue(os.path.exists(get_preset_path("Foo Device", "preset2 copy 3")))

    def test_copy_preset_should_not_append_copy_twice(self):
        prepare_presets()
        self.assertTrue(os.path.isfile(get_preset_path("Foo Device", "preset2")))

        self.data_manager.load_group("Foo Device 2")
        self.data_manager.load_preset("preset2")
        self.controller.copy_preset()  # creates "preset2 copy"
        self.controller.copy_preset()  # creates "preset2 copy 2" not "preset2 copy copy"

        self.assertTrue(os.path.exists(get_preset_path("Foo Device", "preset2")))
        self.assertTrue(os.path.exists(get_preset_path("Foo Device", "preset2 copy")))
        self.assertTrue(os.path.exists(get_preset_path("Foo Device", "preset2 copy 2")))

    def test_copy_preset_should_not_append_copy_to_copy_with_number(self):
        prepare_presets()
        self.assertTrue(os.path.isfile(get_preset_path("Foo Device", "preset2")))

        self.data_manager.load_group("Foo Device 2")
        self.data_manager.load_preset("preset2")
        self.controller.copy_preset()  # creates "preset2 copy"
        self.data_manager.load_preset("preset2")
        self.controller.copy_preset()  # creates "preset2 copy 2"
        self.controller.copy_preset()  # creates "preset2 copy 3" not "preset2 copy 2 copy"

        self.assertTrue(os.path.exists(get_preset_path("Foo Device", "preset2")))
        self.assertTrue(os.path.exists(get_preset_path("Foo Device", "preset2 copy")))
        self.assertTrue(os.path.exists(get_preset_path("Foo Device", "preset2 copy 2")))
        self.assertTrue(os.path.exists(get_preset_path("Foo Device", "preset2 copy 3")))

    def test_rename_preset(self):
        prepare_presets()
        self.assertTrue(os.path.isfile(get_preset_path("Foo Device", "preset2")))
        self.assertFalse(os.path.exists(get_preset_path("Foo Device", "foo")))

        self.data_manager.load_group("Foo Device 2")
        self.data_manager.load_preset("preset2")
        self.controller.rename_preset(new_name="foo")

        self.assertFalse(os.path.exists(get_preset_path("Foo Device", "preset2")))
        self.assertTrue(os.path.exists(get_preset_path("Foo Device", "foo")))

    def test_rename_preset_should_pick_available_name(self):
        prepare_presets()
        self.assertTrue(os.path.exists(get_preset_path("Foo Device", "preset2")))
        self.assertTrue(os.path.exists(get_preset_path("Foo Device", "preset3")))
        self.assertFalse(os.path.exists(get_preset_path("Foo Device", "preset3 2")))

        self.data_manager.load_group("Foo Device")
        self.data_manager.load_preset("preset2")
        self.controller.rename_preset(new_name="preset3")

        self.assertFalse(os.path.exists(get_preset_path("Foo Device", "preset2")))
        self.assertTrue(os.path.exists(get_preset_path("Foo Device", "preset3")))
        self.assertTrue(os.path.exists(get_preset_path("Foo Device", "preset3 2")))

    def test_rename_preset_should_not_rename_to_empty_name(self):
        prepare_presets()
        self.assertTrue(os.path.exists(get_preset_path("Foo Device", "preset2")))

        self.data_manager.load_group("Foo Device")
        self.data_manager.load_preset("preset2")
        self.controller.rename_preset(new_name="")

        self.assertTrue(os.path.exists(get_preset_path("Foo Device", "preset2")))

    def test_rename_preset_should_not_update_same_name(self):
        """when the new name is the same as the current name"""
        prepare_presets()
        self.assertTrue(os.path.exists(get_preset_path("Foo Device", "preset2")))

        self.data_manager.load_group("Foo Device 2")
        self.data_manager.load_preset("preset2")
        self.controller.rename_preset(new_name="preset2")

        self.assertTrue(os.path.exists(get_preset_path("Foo Device", "preset2")))
        self.assertFalse(os.path.exists(get_preset_path("Foo Device", "preset2 2")))

    def test_on_add_preset_uses_default_name(self):
        self.assertFalse(
            os.path.exists(get_preset_path("Foo Device", DEFAULT_PRESET_NAME))
        )

        self.data_manager.load_group("Foo Device 2")

        self.controller.add_preset()
        self.assertTrue(os.path.exists(get_preset_path("Foo Device", "new preset")))

    def test_on_add_preset_uses_provided_name(self):
        self.assertFalse(os.path.exists(get_preset_path("Foo Device", "foo")))

        self.data_manager.load_group("Foo Device 2")

        self.controller.add_preset(name="foo")
        self.assertTrue(os.path.exists(get_preset_path("Foo Device", "foo")))

    def test_on_add_preset_shows_permission_error_status(self):
        self.data_manager.load_group("Foo Device 2")

        msg = None

        def f(data):
            nonlocal msg
            msg = data

        self.message_broker.subscribe(MessageType.status, f)
        mock = MagicMock(side_effect=PermissionError)
        with patch("inputremapper.configs.preset.Preset.save", mock):
            self.controller.add_preset("foo")

        mock.assert_called()
        self.assertIsNotNone(msg)
        self.assertIn("Permission denied", msg.msg)

    def test_on_update_mapping(self):
        """update_mapping should call data_manager.update_mapping
        this ensures mapping_changed is emitted
        """
        prepare_presets()
        self.data_manager.load_group("Foo Device 2")
        self.data_manager.load_preset("preset2")
        self.data_manager.load_mapping(combination=EventCombination("1,4,1"))

        with patch.object(self.data_manager, "update_mapping") as mock:
            self.controller.update_mapping(
                name="foo",
                output_symbol="f",
                release_timeout=0.3,
            )
            mock.assert_called_once()

    def test_create_mapping_will_load_the_created_mapping(self):
        prepare_presets()
        self.data_manager.load_group("Foo Device 2")
        self.data_manager.load_preset("preset2")

        calls: List[MappingData] = []

        def f(data):
            calls.append(data)

        self.message_broker.subscribe(MessageType.mapping, f)
        self.controller.create_mapping()

        self.assertEqual(calls[-1], UIMapping(**MAPPING_DEFAULTS))

    def test_create_mapping_should_not_create_multiple_empty_mappings(self):
        prepare_presets()
        self.data_manager.load_group("Foo Device 2")
        self.data_manager.load_preset("preset2")
        self.controller.create_mapping()  # create a first empty mapping

        calls = []

        def f(data):
            calls.append(data)

        self.message_broker.subscribe(MessageType.mapping, f)
        self.message_broker.subscribe(MessageType.preset, f)

        self.controller.create_mapping()  # try to create a second one
        self.assertEqual(len(calls), 0)

    def test_delete_mapping_asks_for_confirmation(self):
        prepare_presets()
        self.message_broker.signal(MessageType.init)
        self.controller.delete_mapping()
        self.user_interface.confirm_delete.assert_called_once()

    def test_deletes_mapping_when_confirmed(self):
        prepare_presets()
        self.assertTrue(os.path.isfile(get_preset_path("Foo Device", "preset2")))

        self.data_manager.load_group("Foo Device 2")
        self.data_manager.load_preset("preset2")
        self.data_manager.load_mapping(EventCombination("1,3,1"))
        self.user_interface.confirm_delete.configure_mock(
            return_value=Gtk.ResponseType.ACCEPT
        )
        self.controller.delete_mapping()
        self.controller.save()

        preset = Preset(get_preset_path("Foo Device", "preset2"))
        preset.load()
        self.assertIsNone(preset.get_mapping(EventCombination("1,3,1")))

    def test_does_not_delete_mapping_when_not_confirmed(self):
        prepare_presets()
        self.assertTrue(os.path.isfile(get_preset_path("Foo Device", "preset2")))

        self.data_manager.load_group("Foo Device 2")
        self.data_manager.load_preset("preset2")
        self.data_manager.load_mapping(EventCombination("1,3,1"))
        self.user_interface.confirm_delete.configure_mock(
            return_value=Gtk.ResponseType.CANCEL
        )

        self.controller.delete_mapping()
        self.controller.save()

        preset = Preset(get_preset_path("Foo Device", "preset2"))
        preset.load()
        self.assertIsNotNone(preset.get_mapping(EventCombination("1,3,1")))

    def test_should_update_combination(self):
        """when combination is free"""
        prepare_presets()
        self.data_manager.load_group("Foo Device 2")
        self.data_manager.load_preset("preset2")
        self.data_manager.load_mapping(EventCombination.from_string("1,3,1"))

        calls: List[CombinationUpdate] = []

        def f(data):
            calls.append(data)

        self.message_broker.subscribe(MessageType.combination_update, f)
        self.controller.update_combination(EventCombination.from_string("1,10,1"))
        self.assertEqual(
            calls[0],
            CombinationUpdate(
                EventCombination.from_string("1,3,1"),
                EventCombination.from_string("1,10,1"),
            ),
        )

    def test_should_not_update_combination(self):
        """when combination is already used"""
        prepare_presets()
        self.data_manager.load_group("Foo Device 2")
        self.data_manager.load_preset("preset2")
        self.data_manager.load_mapping(EventCombination.from_string("1,3,1"))

        calls: List[CombinationUpdate] = []

        def f(data):
            calls.append(data)

        self.message_broker.subscribe(MessageType.combination_update, f)
        self.controller.update_combination(EventCombination.from_string("1,4,1"))
        self.assertEqual(len(calls), 0)

    def test_key_recording_disables_gui_shortcuts(self):
        self.message_broker.signal(MessageType.init)
        self.user_interface.disconnect_shortcuts.assert_not_called()
        self.controller.start_key_recording()
        self.user_interface.disconnect_shortcuts.assert_called_once()

    def test_key_recording_enables_gui_shortcuts_when_finished(self):
        self.message_broker.signal(MessageType.init)
        self.controller.start_key_recording()

        self.user_interface.connect_shortcuts.assert_not_called()
        self.message_broker.signal(MessageType.recording_finished)
        self.user_interface.connect_shortcuts.assert_called_once()

    def test_key_recording_enables_gui_shortcuts_when_stopped(self):
        self.message_broker.signal(MessageType.init)
        self.controller.start_key_recording()

        self.user_interface.connect_shortcuts.assert_not_called()
        self.controller.stop_key_recording()
        self.user_interface.connect_shortcuts.assert_called_once()

    def test_key_recording_updates_mapping_combination(self):
        prepare_presets()
        self.data_manager.load_group("Foo Device 2")
        self.data_manager.load_preset("preset2")
        self.data_manager.load_mapping(EventCombination.from_string("1,3,1"))

        calls: List[CombinationUpdate] = []

        def f(data):
            calls.append(data)

        self.message_broker.subscribe(MessageType.combination_update, f)

        self.controller.start_key_recording()
        self.message_broker.send(
            CombinationRecorded(EventCombination.from_string("1,10,1"))
        )
        self.assertEqual(
            calls[0],
            CombinationUpdate(
                EventCombination.from_string("1,3,1"),
                EventCombination.from_string("1,10,1"),
            ),
        )
        self.message_broker.send(
            CombinationRecorded(EventCombination.from_string("1,10,1+1,3,1"))
        )
        self.assertEqual(
            calls[1],
            CombinationUpdate(
                EventCombination.from_string("1,10,1"),
                EventCombination.from_string("1,10,1+1,3,1"),
            ),
        )

    def test_no_key_recording_when_not_started(self):
        prepare_presets()
        self.data_manager.load_group("Foo Device 2")
        self.data_manager.load_preset("preset2")
        self.data_manager.load_mapping(EventCombination.from_string("1,3,1"))

        calls: List[CombinationUpdate] = []

        def f(data):
            calls.append(data)

        self.message_broker.subscribe(MessageType.combination_update, f)

        self.message_broker.send(
            CombinationRecorded(EventCombination.from_string("1,10,1"))
        )
        self.assertEqual(len(calls), 0)

    def test_key_recording_stops_when_finished(self):
        prepare_presets()
        self.data_manager.load_group("Foo Device 2")
        self.data_manager.load_preset("preset2")
        self.data_manager.load_mapping(EventCombination.from_string("1,3,1"))

        calls: List[CombinationUpdate] = []

        def f(data):
            calls.append(data)

        self.message_broker.subscribe(MessageType.combination_update, f)

        self.controller.start_key_recording()
        self.message_broker.send(
            CombinationRecorded(EventCombination.from_string("1,10,1"))
        )
        self.message_broker.signal(MessageType.recording_finished)
        self.message_broker.send(
            CombinationRecorded(EventCombination.from_string("1,10,1+1,3,1"))
        )

        self.assertEqual(len(calls), 1)  # only the first was processed

    def test_key_recording_stops_when_stopped(self):
        prepare_presets()
        self.data_manager.load_group("Foo Device 2")
        self.data_manager.load_preset("preset2")
        self.data_manager.load_mapping(EventCombination.from_string("1,3,1"))

        calls: List[CombinationUpdate] = []

        def f(data):
            calls.append(data)

        self.message_broker.subscribe(MessageType.combination_update, f)

        self.controller.start_key_recording()
        self.message_broker.send(
            CombinationRecorded(EventCombination.from_string("1,10,1"))
        )
        self.controller.stop_key_recording()
        self.message_broker.send(
            CombinationRecorded(EventCombination.from_string("1,10,1+1,3,1"))
        )

        self.assertEqual(len(calls), 1)  # only the first was processed

    def test_start_injecting_shows_status_when_preset_empty(self):
        self.data_manager.load_group("Foo Device 2")
        self.data_manager.create_preset("foo")
        self.data_manager.load_preset("foo")
        calls: List[StatusData] = []

        def f(data):
            calls.append(data)

        self.message_broker.subscribe(MessageType.status, f)

        def f2():
            raise AssertionError("Injection started unexpectedly")

        self.data_manager.start_injecting = f2
        self.controller.start_injecting()

        self.assertEqual(
            calls[-1], StatusData(CTX_ERROR, _("You need to add keys and save first"))
        )

    def test_start_injecting_warns_about_btn_left(self):
        self.data_manager.load_group("Foo Device 2")
        self.data_manager.create_preset("foo")
        self.data_manager.load_preset("foo")
        self.data_manager.create_mapping()
        self.data_manager.update_mapping(
            event_combination=EventCombination(InputEvent.btn_left()),
            target_uinput="keyboard",
            output_symbol="a",
        )
        calls: List[StatusData] = []

        def f(data):
            calls.append(data)

        self.message_broker.subscribe(MessageType.status, f)

        def f2():
            raise AssertionError("Injection started unexpectedly")

        self.data_manager.start_injecting = f2
        self.controller.start_injecting()

        self.assertEqual(calls[-1].ctx_id, CTX_ERROR)
        self.assertIn("BTN_LEFT", calls[-1].tooltip)

    def test_start_injecting_starts_with_btn_left_on_second_try(self):
        self.data_manager.load_group("Foo Device 2")
        self.data_manager.create_preset("foo")
        self.data_manager.load_preset("foo")
        self.data_manager.create_mapping()
        self.data_manager.update_mapping(
            event_combination=EventCombination(InputEvent.btn_left()),
            target_uinput="keyboard",
            output_symbol="a",
        )

        with patch.object(self.data_manager, "start_injecting") as mock:
            self.controller.start_injecting()
            mock.assert_not_called()
            self.controller.start_injecting()
            mock.assert_called_once()

    def test_start_injecting_starts_with_btn_left_when_mapped_to_other_button(self):
        self.data_manager.load_group("Foo Device 2")
        self.data_manager.create_preset("foo")
        self.data_manager.load_preset("foo")
        self.data_manager.create_mapping()
        self.data_manager.update_mapping(
            event_combination=EventCombination(InputEvent.btn_left()),
            target_uinput="keyboard",
            output_symbol="a",
        )
        self.data_manager.create_mapping()
        self.data_manager.load_mapping(EventCombination.empty_combination())
        self.data_manager.update_mapping(
            event_combination=EventCombination.from_string("1,5,1"),
            target_uinput="mouse",
            output_symbol="BTN_LEFT",
        )

        mock = MagicMock(return_value=True)
        self.data_manager.start_injecting = mock
        self.controller.start_injecting()
        mock.assert_called()

    def test_start_injecting_shows_status(self):
        prepare_presets()
        self.data_manager.load_group("Foo Device 2")
        self.data_manager.load_preset("preset2")
        calls: List[StatusData] = []

        def f(data):
            calls.append(data)

        self.message_broker.subscribe(MessageType.status, f)
        mock = MagicMock(return_value=True)
        self.data_manager.start_injecting = mock
        self.controller.start_injecting()

        mock.assert_called()
        self.assertEqual(calls[0], StatusData(CTX_APPLY, _("Starting injection...")))

    def test_start_injecting_shows_failure_status(self):
        prepare_presets()
        self.data_manager.load_group("Foo Device 2")
        self.data_manager.load_preset("preset2")
        calls: List[StatusData] = []

        def f(data):
            calls.append(data)

        self.message_broker.subscribe(MessageType.status, f)
        mock = MagicMock(return_value=False)
        self.data_manager.start_injecting = mock
        self.controller.start_injecting()

        mock.assert_called()
        self.assertEqual(
            calls[0],
            StatusData(
                CTX_APPLY,
                _("Failed to apply preset %s") % self.data_manager.active_preset.name,
            ),
        )

    def test_start_injecting_adds_timeout_to_update_injector_status(self):
        prepare_presets()
        self.data_manager.load_group("Foo Device 2")
        self.data_manager.load_preset("preset2")

        with patch("inputremapper.gui.controller.GLib.timeout_add") as mock:
            self.controller.start_injecting()
            mock.assert_called_with(100, self.controller.show_injection_result)

    def test_stop_injecting_shows_status(self):
        prepare_presets()
        self.data_manager.load_group("Foo Device 2")
        self.data_manager.load_preset("preset2")
        calls: List[StatusData] = []

        def f(data):
            calls.append(data)

        self.message_broker.subscribe(MessageType.status, f)
        mock = MagicMock()
        self.data_manager.stop_injecting = mock
        self.controller.stop_injecting()

        mock.assert_called()
        self.assertEqual(
            calls[-1], StatusData(CTX_APPLY, _("Applied the system default"))
        )

    def test_show_injection_result(self):
        prepare_presets()
        self.data_manager.load_group("Foo Device 2")
        self.data_manager.load_preset("preset2")
        self.controller.start_injecting()

        mock = MagicMock(return_value=RUNNING)
        self.data_manager.get_state = mock
        calls: List[StatusData] = []

        def f(data):
            calls.append(data)

        self.message_broker.subscribe(MessageType.status, f)

        assert not self.controller.show_injection_result()
        self.assertEqual(calls[-1].msg, _("Applied preset %s") % "preset2")

        mock.return_value = FAILED
        assert not self.controller.show_injection_result()
        self.assertEqual(calls[-1].msg, _("Failed to apply preset %s") % "preset2")

        mock.return_value = NO_GRAB
        assert not self.controller.show_injection_result()
        self.assertEqual(calls[-1].msg, "The device was not grabbed")

        mock.return_value = UPGRADE_EVDEV
        assert not self.controller.show_injection_result()
        self.assertEqual(calls[-1].msg, "Upgrade python-evdev")

        mock.return_value = UNKNOWN
        assert self.controller.show_injection_result()

    def test_close(self):
        mock_save = MagicMock()
        listener = MagicMock()
        self.message_broker.subscribe(MessageType.terminate, listener)
        self.data_manager.save = mock_save

        self.controller.close()
        mock_save.assert_called()
        listener.assert_called()

    def test_set_autoload_refreshes_service_config(self):
        prepare_presets()
        self.data_manager.load_group("Foo Device 2")
        self.data_manager.load_preset("preset2")

        with patch.object(self.data_manager, "refresh_service_config_path") as mock:
            self.controller.set_autoload(True)
            mock.assert_called()
