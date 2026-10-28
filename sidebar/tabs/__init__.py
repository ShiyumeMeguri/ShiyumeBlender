from . import animation
from . import curve
from . import endfield
from . import mesh
from . import misc
from . import shader
from . import uv
from . import uv_transfer

TABS = (
    animation.TAB,
    mesh.TAB,
    shader.TAB,
    endfield.TAB,
    uv.TAB,
    uv_transfer.TAB,
    curve.TAB,
    misc.TAB,
)
BY_KEY = {tab.key: tab for tab in TABS}
PLACEMENTS = endfield.PLACEMENTS
