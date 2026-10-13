async def test_removing_the_entry_closes_the_camera_sessions(hass, camera, entry):
    await camera.wait_clients(1)

    await hass.remove_entry(entry.entry_id)

    await camera.wait_clients(0)
