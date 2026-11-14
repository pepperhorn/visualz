"""T3 seam: neutral overlay; all GL methods run on the main thread."""

from PIL import Image


def render_preview(template, variables, size):
    """Return RGBA Pillow image at (width,height), no GL or shared mutable state.

    template is validated OverlayTemplate; variables contains now-playing values.
    T3 replaces the transparent placeholder with the same layout used on stage.
    """
    return Image.new("RGBA", size)


class Overlay:
    """Overlay(context, data_dir): draw(state, now) uses immutable Store snapshot.

    now is monotonic seconds; draw composites onto current framebuffer without
    swapping. close() releases GPU resources. T3 implements layout and animation.
    """

    def __init__(self, context, data_dir):
        self.context, self.data_dir = context, data_dir

    def draw(self, state, now):
        pass

    def close(self):
        pass
