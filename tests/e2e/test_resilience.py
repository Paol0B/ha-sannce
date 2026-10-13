from bench.hass_client import DOMAIN, wait_for

NEW_PASSWORD = "bench-new-pass"


async def reauth_flow(hass, entry_id):
    for flow in await hass.flows():
        context = flow["context"]
        if (
            flow["handler"] == DOMAIN
            and context.get("source") == "reauth"
            and context.get("entry_id") == entry_id
        ):
            return flow
    return None


async def test_a_drop_makes_entities_unavailable_until_the_camera_returns(
    hass, camera, entry
):
    sensor, light = entry.entity_ids["motion"], entry.entity_ids["floodlight"]
    await hass.wait_state(light, "off", timeout=5)

    await camera.drop(5)
    await hass.wait_state(sensor, "unavailable", timeout=3)
    await hass.wait_state(light, "unavailable", timeout=3)
    await camera.settings(light=True)

    # reconnect tries at 0, 1, 3 and 7 s; the 7 s try finds the camera back
    await hass.wait_available(sensor, timeout=30)
    await hass.wait_state(light, "on", timeout=20)


async def test_a_changed_password_opens_reauth_and_the_new_one_reloads(
    hass, camera, entry
):
    sensor = entry.entity_ids["motion"]
    await hass.wait_available(sensor, timeout=30)

    await camera.set_password(NEW_PASSWORD)
    # open sessions outlive a password change, so drop them to force a new login
    await camera.drop(0)
    flow = await wait_for(
        lambda: reauth_flow(hass, entry.entry_id),
        lambda found: found is not None,
        30,
        "waiting for a reauth flow",
    )
    result = await hass.configure_flow(flow["flow_id"], {"password": NEW_PASSWORD})

    assert (result["type"], result["reason"]) == ("abort", "reauth_successful")
    await hass.wait_available(sensor, timeout=30)
    assert [listed["state"] for listed in await hass.entries()] == ["loaded"]
