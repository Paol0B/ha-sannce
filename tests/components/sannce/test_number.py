import pytest
from homeassistant.components.number import (
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.exceptions import HomeAssistantError

from custom_components.sannce import lib

from . import setup_integration

VOLUME = "number.i91fw_volume"
SENSITIVITY = "number.i91fw_motion_sensitivity"


async def set_value(hass, entity_id, value):
    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: entity_id, ATTR_VALUE: value},
        blocking=True,
    )


async def test_volume_shows_and_sets_the_camera_volume(
    hass, identified_entry, mock_camera
):
    await setup_integration(hass, identified_entry)
    assert hass.states.get(VOLUME).state == "80"

    await set_value(hass, VOLUME, 30)

    mock_camera.set_volume.assert_awaited_with(30)
    assert hass.states.get(VOLUME).state == "30"


async def test_motion_sensitivity_shows_the_camera_level(
    hass, identified_entry, mock_camera
):
    await setup_integration(hass, identified_entry)
    assert hass.states.get(SENSITIVITY).state == "76"


async def test_motion_sensitivity_sets_the_camera(hass, identified_entry, mock_camera):
    await setup_integration(hass, identified_entry)

    await set_value(hass, SENSITIVITY, 100)

    mock_camera.set_sensitivity.assert_awaited_with(100)
    assert hass.states.get(SENSITIVITY).state == "100"


async def test_motion_sensitivity_sends_a_fraction_as_a_whole_number(
    hass, identified_entry, mock_camera
):
    await setup_integration(hass, identified_entry)

    await set_value(hass, SENSITIVITY, 75.6)

    (level,) = mock_camera.set_sensitivity.await_args.args
    assert level == 76
    assert type(level) is int
    assert hass.states.get(SENSITIVITY).state == "76"


async def test_numbers_range_0_to_100(hass, identified_entry, mock_camera):
    await setup_integration(hass, identified_entry)
    for entity_id in (VOLUME, SENSITIVITY):
        attributes = hass.states.get(entity_id).attributes
        assert (attributes["min"], attributes["max"], attributes["step"]) == (0, 100, 1)


async def test_a_refused_write_raises_a_readable_error(
    hass, identified_entry, mock_camera, translations
):
    mock_camera.set_volume.side_effect = lib.ProtocolError("refused")
    await setup_integration(hass, identified_entry)
    with pytest.raises(HomeAssistantError, match="refused"):
        await set_value(hass, VOLUME, 10)


async def test_no_volume_without_the_cap(hass, identified_entry, mock_camera):
    mock_camera.caps = mock_camera.caps - {"volume"}
    await setup_integration(hass, identified_entry)
    assert hass.states.get(VOLUME) is None
