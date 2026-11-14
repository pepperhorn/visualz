"""Profile defaults shared by T2 and media; auto resolves to detection or low.

pi_model='pi2' selects the low profile's smaller internal target. High internal
resolution follows output; callers still honour explicit settings dimensions and
per-mode quality. No hardware detection or GL imports live in this data module.
"""

from copy import deepcopy

PROFILES = {
    "low": dict(
        output=(1280, 720),
        internal=(480, 270),
        pi2_internal=(320, 180),
        target_fps=30,
        quality="low",
        clip_size=(480, 270),
        clip_fps=15,
        logo_size=192,
        logo_fps=10,
        logo_frames=100,
        picture_size=2048,
        archive_bytes=64 * 1024 * 1024,
    ),
    "high": dict(
        output=(1920, 1080),
        internal="output",
        target_fps=60,
        quality="high",
        clip_size=(1280, 720),
        clip_fps=30,
        logo_size=512,
        logo_fps=30,
        logo_frames=300,
        picture_size=4096,
        archive_bytes=384 * 1024 * 1024,
    ),
}


def resolve_profile(requested="auto", detected=None):
    name = detected if requested == "auto" else requested
    if not isinstance(name, str) or name not in PROFILES:
        name = "low"
    return name


def profile_defaults(profile="low", output=None, pi_model=None):
    values = deepcopy(PROFILES[resolve_profile(profile)])
    output = tuple(output or values["output"])
    values["output"] = output
    if values["internal"] == "output":
        values["internal"] = tuple(min(v, cap) for v, cap in zip(output, (1920, 1080)))
    elif pi_model == "pi2":
        values["internal"] = values["pi2_internal"]
    return values


def stage_size(settings, detected=None):
    defaults = profile_defaults(resolve_profile(settings["hardware_profile"], detected))
    stage = settings["stage"]
    return tuple(
        default if stage[key] == "auto" else stage[key]
        for key, default in zip(("width", "height"), defaults["output"])
    )


def media_options(settings, runtime):
    name = resolve_profile(
        settings["hardware_profile"], runtime.status().get("stage", {}).get("hardware_profile")
    )
    values = profile_defaults(name)
    return {
        key: values[key]
        for key in ("clip_size", "clip_fps", "logo_size", "logo_fps", "logo_frames", "picture_size")
    }


def archive_limit(settings, runtime):
    return profile_defaults(
        resolve_profile(
            settings["hardware_profile"], runtime.status().get("stage", {}).get("hardware_profile")
        )
    )["archive_bytes"]
