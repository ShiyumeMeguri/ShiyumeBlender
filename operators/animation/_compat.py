"""Blender 4.x vs 5.x Action API compatibility.

Blender 5.0 replaced the legacy ``Action.fcurves`` collection with the slotted
animation system: ``Action.layers[i].strips[j].channelbags[k].fcurves``.
Legacy ``Action.fcurves`` is no longer present.

This module provides minimal helpers so the rest of the addon doesn't need to
care which API it is talking to.
"""

import bpy


def iter_action_fcurves(action):
    """Yield ``(owner, fcurve)`` for every fcurve in ``action``.

    ``owner`` is the collection on which ``.remove(fcurve)`` works, i.e.
    ``action.fcurves`` on legacy API or ``channelbag.fcurves`` on the slotted
    API. Iterate eagerly (list) when you plan to mutate during the loop.
    """
    if action is None:
        return
    # Legacy (Blender 4.x and earlier)
    if hasattr(action, 'fcurves'):
        for fc in action.fcurves:
            yield action.fcurves, fc
        return
    # Slotted (Blender 5.x+)
    if hasattr(action, 'layers'):
        for layer in action.layers:
            for strip in layer.strips:
                if hasattr(strip, 'channelbags'):
                    for cb in strip.channelbags:
                        for fc in cb.fcurves:
                            yield cb.fcurves, fc


def list_action_fcurves(action):
    """Snapshot of every ``(owner, fcurve)`` so you can safely mutate."""
    return list(iter_action_fcurves(action))


def remove_fcurve(owner, fcurve):
    """Remove ``fcurve`` from its collection."""
    owner.remove(fcurve)


def get_active_action(obj):
    """Return the active action on ``obj`` or None."""
    if obj is None:
        return None
    ad = getattr(obj, 'animation_data', None)
    if ad is None:
        return None
    return ad.action
